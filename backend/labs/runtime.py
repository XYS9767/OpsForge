"""Kubernetes-backed personal practice workspace, separate from application namespace."""
import base64
import os
import posixpath
import shlex
import threading
import time
import uuid
import json
import logging
import re
from contextlib import contextmanager
from core.files import validate_files
from core.errors import ApiError


class Runtime:
    def __init__(self, load_state=None, save_state=None):
        self.enabled = os.getenv("LAB_BACKEND", "simulation") == "kubernetes"
        self.namespace = os.getenv("LAB_NAMESPACE", "opsforge-practice")
        self.docker_namespace = os.getenv("DOCKER_LAB_NAMESPACE", "opsforge-docker")
        self.distributed_namespace = os.getenv("DISTRIBUTED_LAB_NAMESPACE", "opsforge-distributed")
        self.distributed = os.getenv("ENABLE_DISTRIBUTED_LAB", "false").lower() == "true"
        self.current_namespace = self.namespace
        self.image = os.getenv("LAB_IMAGE", "opsforge-lab:1.0.0")
        self.docker = os.getenv("ENABLE_DOCKER_LAB", "false").lower() == "true"
        self.cluster = os.getenv("ENABLE_CLUSTER_LAB", "false").lower() == "true"
        self.lock = threading.RLock()
        self.current = None
        self.last_used = 0
        self.pending = []
        self._staging = False
        self._save_state = save_state or (lambda state: None)
        state = load_state() if load_state else {}
        self.current = state.get("current")
        self.current_namespace = state.get("namespace", self.namespace)
        self.last_used = state.get("last_used", 0)
        self.pending = state.get("pending", [])
        if self.enabled:
            threading.Thread(target=self._reaper, daemon=True).start()

    def status(self):
        return {"enabled": self.enabled, "backend": "kubernetes" if self.enabled else "simulation",
                "docker_enabled": self.enabled and self.docker, "cluster_enabled": self.enabled and self.cluster,
                "distributed_enabled": self.enabled and self.distributed, "namespace": self.namespace,
                "note": "真实实验为个人共享练习命名空间，仅用于练习；同时保留一个工作区。" if self.enabled else "当前为模拟模式。部署到 Kubernetes 并配置实验镜像后可开启真实 Linux / kubectl / Helm / 代码执行。"}

    def _api(self):
        from kubernetes import client, config
        config.load_incluster_config()
        return client.CoreV1Api()

    def manifest(self, name, docker=False, cluster=False, distributed=False):
        if distributed and (docker or cluster):
            raise ValueError('分布式服务工作区不能与特权 Docker/集群工作区混用')
        security = {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                    "capabilities": {"drop": ["ALL"]}, "runAsNonRoot": True,
                    "runAsUser": 1000, "runAsGroup": 1000}
        container = {
            "name": "workspace", "image": self.image, "imagePullPolicy": "IfNotPresent",
            "command": ["/usr/local/bin/setup-workspace"],
            "workingDir": "/workspace", "securityContext": security,
            "env": [{"name": "HOME", "value": "/workspace"}, {"name": "GOCACHE", "value": "/workspace/.cache/go"},
                    {"name": "PRACTICE_NAMESPACE", "value": self.namespace},
                    {"name": "KUBECONFIG", "value": "/workspace/.kube/config"},
                    {"name": "HELM_DRIVER", "value": "configmap"}],
            "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"cpu": "1", "memory": "768Mi", "ephemeral-storage": "2Gi"}},
            "volumeMounts": [{"name": "work", "mountPath": "/workspace"}, {"name": "tmp", "mountPath": "/tmp"}],
        }
        spec = {"serviceAccountName": "opsforge-learner", "automountServiceAccountToken": True,
                "restartPolicy": "Never", "activeDeadlineSeconds": 3600, "terminationGracePeriodSeconds": 5,
                "securityContext": {"fsGroup": 1000, "seccompProfile": {"type": "RuntimeDefault"}},
                "containers": [container], "volumes": [{"name": "work", "emptyDir": {"sizeLimit": "1Gi"}},
                                                       {"name": "tmp", "emptyDir": {"sizeLimit": "512Mi"}}]}
        selector = os.getenv('LAB_NODE_SELECTOR', '')
        if selector:
            if '=' not in selector or any(not x.strip() for x in selector.split('=', 1)):
                raise ValueError('LAB_NODE_SELECTOR 应为 label=value')
            key, value = selector.split('=', 1)
            spec['nodeSelector'] = {key: value}
        if docker:
            if not self.docker:
                raise ValueError("Docker 实验未开启，请先阅读部署说明中的专用实验节点要求")
            container["env"].append({"name": "DOCKER_HOST", "value": "tcp://127.0.0.1:2375"})
            spec["serviceAccountName"] = "default"
            spec["automountServiceAccountToken"] = False
            spec["containers"].append({
                "name": "docker", "image": os.getenv("DIND_IMAGE", "docker:27-dind"),
                "args": ["--host=tcp://127.0.0.1:2375", "--tls=false"],
                "env": [{"name": "DOCKER_TLS_CERTDIR", "value": ""}],
                "securityContext": {"privileged": True},
                "resources": {"requests": {"cpu": "100m", "memory": "256Mi"}, "limits": {"cpu": "1", "memory": "1Gi", "ephemeral-storage": "3Gi"}},
            })
            selector = os.getenv("DOCKER_NODE_SELECTOR", "")
            if not selector or "=" not in selector:
                raise ValueError("Docker 实验要求配置 DOCKER_NODE_SELECTOR，例如 opsforge-lab=true")
            key, value = selector.split("=", 1)
            spec["nodeSelector"] = {key: value}
        if cluster:
            if not self.cluster:
                raise ValueError("独立 Kubernetes 实验未开启，需要专用实验节点")
            spec["serviceAccountName"] = "default"
            spec["automountServiceAccountToken"] = False
            selector = os.getenv("DOCKER_NODE_SELECTOR", "")
            if not selector or "=" not in selector:
                raise ValueError("独立集群要求配置专用实验节点选择器")
            key, value = selector.split("=", 1)
            spec["nodeSelector"] = {key: value}
            container['resources']['requests']['ephemeral-storage'] = '128Mi'
            container['env'].append({'name':'OPSF_NODE_IMAGE','value':os.getenv('NODE_LAB_IMAGE','busybox:1.36.1')})
            server_command = '/usr/local/bin/opsforge-k3s-bootstrap' if os.getenv('K3S_PRELOAD_IMAGES','false').lower() == 'true' else 'k3s'
            spec["containers"].append({
                "name": "k3s", "image": os.getenv("K3S_IMAGE", "rancher/k3s:v1.34.1-k3s1"),
                "command": [server_command, "server", "--disable=traefik", "--disable=servicelb",
                            "--disable=metrics-server", "--write-kubeconfig=/shared/.kube/config",
                            "--write-kubeconfig-mode=0644", "--tls-san=127.0.0.1", "--node-name=practice",
                            "--node-label=hw=compute", "--kubelet-arg=sync-frequency=5s",
                            "--service-cidr=10.241.0.0/16", "--cluster-cidr=10.242.0.0/16"],
                "securityContext": {"privileged": True},
                "resources": {"requests": {"cpu": "250m", "memory": "512Mi", "ephemeral-storage": "512Mi"}, "limits": {"cpu": "2", "memory": "2Gi", "ephemeral-storage": "4Gi"}},
                "volumeMounts": [{"name": "work", "mountPath": "/shared"}, {"name": "k3s-data", "mountPath": "/var/lib/rancher/k3s"}],
                "readinessProbe": {"exec": {"command": ["kubectl", "--kubeconfig=/shared/.kube/config", "wait",
                                                          "--for=condition=Ready", "node/practice", "--timeout=2s"]},
                                   "initialDelaySeconds": 10, "periodSeconds": 5, "timeoutSeconds": 4},
            })
            spec["volumes"].append({"name": "k3s-data", "emptyDir": {"sizeLimit": "4Gi"}})
        if distributed:
            if not self.distributed:
                raise ValueError('分布式服务实验未开启，请配置独立实验节点和高内存资源')
            selector = os.getenv('DISTRIBUTED_NODE_SELECTOR', '')
            if '=' not in selector or any(not part.strip() for part in selector.split('=', 1)):
                raise ValueError('分布式服务实验要求配置 DISTRIBUTED_NODE_SELECTOR=label=value')
            key, value = selector.split('=', 1)
            spec['nodeSelector'] = {key: value}
            spec['serviceAccountName'] = 'default'
            spec['automountServiceAccountToken'] = False
            container['env'] = [item for item in container['env']
                                if item['name'] not in ('KUBECONFIG', 'PRACTICE_NAMESPACE')]
            container['resources'] = {'requests': {'cpu': '500m', 'memory': '1Gi'},
                                     'limits': {'cpu': '2', 'memory': '5Gi', 'ephemeral-storage': '6Gi'}}
            spec['volumes'] = [{'name': 'work', 'emptyDir': {'sizeLimit': '4Gi'}},
                               {'name': 'tmp', 'emptyDir': {'sizeLimit': '1Gi'}}]
        for tool, variable in (('clickhouse', 'CLICKHOUSE_TOOL_PVC'), ('loki', 'LOKI_TOOL_PVC'), ('envoy', 'ENVOY_TOOL_PVC'), ('envoy-compat', 'ENVOY_COMPAT_TOOL_PVC'), ('zabbix_agentd', 'ZABBIX_AGENTD_TOOL_PVC'), ('zabbix_agentd_tls', 'ZABBIX_AGENT_TLS_TOOL_PVC'), ('kube-controller-manager', 'KUBE_CONTROLLER_MANAGER_TOOL_PVC'), ('coredns', 'COREDNS_TOOL_PVC'), ('qemu-x86_64', 'QEMU_X86_64_TOOL_PVC')):
            claim = os.getenv(variable, '')
            if claim:
                if not re.fullmatch(r'[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?', claim):
                    raise ValueError(variable + ' 必须是1至63位小写DNS标签')
                volume_name = tool.replace('_', '-') + '-tool'
                spec['volumes'].append({'name': volume_name, 'persistentVolumeClaim': {
                    'claimName': claim, 'readOnly': True}})
                container['volumeMounts'].append({'name': volume_name, 'mountPath': '/usr/local/bin/' + tool,
                    'subPath': tool, 'readOnly': True})
                if tool == 'zabbix_agentd_tls':
                    container['volumeMounts'].append({'name': volume_name,
                        'mountPath': '/usr/lib/x86_64-linux-gnu/libmodbus.so.5',
                        'subPath': 'zabbix-tls-libs/libmodbus.so.5', 'readOnly': True})
        chromium_claim = os.getenv('CHROMIUM_HEADLESS_TOOL_PVC', '')
        if chromium_claim:
            if not re.fullmatch(r'[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?', chromium_claim):
                raise ValueError('CHROMIUM_HEADLESS_TOOL_PVC 必须是1至63位小写DNS标签')
            if docker or cluster or distributed:
                raise ValueError('Chromium headless工具仅适用于普通隔离工作区')
            spec['volumes'].append({'name': 'chromium-headless-tool', 'persistentVolumeClaim': {
                'claimName': chromium_claim, 'readOnly': True}})
            for destination, subpath in (
                    ('/opt/opsforge-chromium', 'chromium-headless'),
                    ('/usr/local/bin/chromium-headless-shell', 'chromium-headless/chromium-headless-shell')):
                container['volumeMounts'].append({'name': 'chromium-headless-tool',
                    'mountPath': destination, 'subPath': subpath, 'readOnly': True})
        postgres_claim = os.getenv('POSTGRESQL_TOOL_PVC', '')
        if postgres_claim:
            if not re.fullmatch(r'[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?', postgres_claim):
                raise ValueError('POSTGRESQL_TOOL_PVC 必须是1至63位小写DNS标签')
            spec['volumes'].append({'name': 'postgres-tool', 'persistentVolumeClaim': {'claimName': postgres_claim, 'readOnly': True}})
            for destination, subpath in (
                ('/opt/opsforge-postgres', 'postgresql-15'),
                ('/usr/local/bin/postgres', 'postgresql-15/usr/lib/postgresql/15/bin/postgres'),
                ('/usr/local/bin/initdb', 'postgresql-15/usr/lib/postgresql/15/bin/initdb'),
                ('/usr/lib/x86_64-linux-gnu/libpq.so.5', 'postgresql-15/usr/lib/x86_64-linux-gnu/libpq.so.5')):
                container['volumeMounts'].append({'name': 'postgres-tool', 'mountPath': destination, 'subPath': subpath, 'readOnly': True})
        zabbix_server_claim = os.getenv('ZABBIX_SERVER_TOOL_PVC', '')
        if zabbix_server_claim:
            if not re.fullmatch(r'[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?', zabbix_server_claim):
                raise ValueError('ZABBIX_SERVER_TOOL_PVC 必须是1至63位小写DNS标签')
            if not postgres_claim or docker or cluster or distributed:
                raise ValueError('Zabbix server工具需要普通隔离工作区及POSTGRESQL_TOOL_PVC')
            spec['volumes'].append({'name': 'zabbix-server-tool', 'persistentVolumeClaim': {
                'claimName': zabbix_server_claim, 'readOnly': True}})
            for destination, subpath in (('/opt/opsforge-zabbix-server', 'zabbix-server-7.0.32'),
                                         ('/usr/local/bin/zabbix_server', 'zabbix-server-tool-launcher')):
                container['volumeMounts'].append({'name': 'zabbix-server-tool',
                    'mountPath': destination, 'subPath': subpath, 'readOnly': True})
        zabbix_php_claim = os.getenv('ZABBIX_PHP_API_TOOL_PVC', '')
        if zabbix_php_claim:
            if not re.fullmatch(r'[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?', zabbix_php_claim):
                raise ValueError('ZABBIX_PHP_API_TOOL_PVC 必须是1至63位小写DNS标签')
            if not postgres_claim or not zabbix_server_claim or docker or cluster or distributed:
                raise ValueError('Zabbix PHP API需要普通隔离工作区及PostgreSQL、Zabbix server工具')
            if os.getenv('LAB_PRIVATE_API_BUDGET', 'false').lower() != 'true':
                raise ValueError('Zabbix PHP API需要显式LAB_PRIVATE_API_BUDGET=true')
            spec['volumes'].append({'name': 'zabbix-php-tool', 'persistentVolumeClaim': {
                'claimName': zabbix_php_claim, 'readOnly': True}})
            for destination, subpath in (
                    ('/opt/opsforge-zabbix-php', 'php-zabbix-tools'),
                    ('/usr/local/bin/php8.2', 'php-zabbix-tools/php8.2')):
                container['volumeMounts'].append({'name': 'zabbix-php-tool',
                    'mountPath': destination, 'subPath': subpath, 'readOnly': True})
        elasticsearch_claim = os.getenv('ELASTICSEARCH_TOOL_PVC', '')
        if elasticsearch_claim:
            if not re.fullmatch(r'[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?', elasticsearch_claim):
                raise ValueError('ELASTICSEARCH_TOOL_PVC 必须是1至63位小写DNS标签')
            if docker or cluster or distributed:
                raise ValueError('Elasticsearch工具仅适用于普通隔离工作区')
            spec['volumes'].append({'name': 'elasticsearch-tool', 'persistentVolumeClaim': {
                'claimName': elasticsearch_claim, 'readOnly': True}})
            for destination, subpath in (
                    ('/opt/opsforge-elasticsearch', 'elasticsearch-8.19.7'),
                    ('/usr/local/bin/elasticsearch', 'elasticsearch-tool-launcher')):
                container['volumeMounts'].append({'name': 'elasticsearch-tool',
                    'mountPath': destination, 'subPath': subpath, 'readOnly': True})
            container['env'].append({'name': 'OPSF_ELASTICSEARCH_HOME', 'value': '/opt/opsforge-elasticsearch'})
        grafana_claim = os.getenv('GRAFANA_TOOL_PVC', '')
        if grafana_claim:
            if not re.fullmatch(r'[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?', grafana_claim):
                raise ValueError('GRAFANA_TOOL_PVC 必须是1至63位小写DNS标签')
            if docker or cluster or distributed:
                raise ValueError('Grafana工具仅适用于普通隔离工作区')
            spec['volumes'].append({'name': 'grafana-tool', 'persistentVolumeClaim': {
                'claimName': grafana_claim, 'readOnly': True}})
            for destination, subpath in (('/opt/opsforge-grafana', 'grafana-11.6.0'),
                                         ('/usr/local/bin/grafana', 'grafana-tool-launcher')):
                container['volumeMounts'].append({'name': 'grafana-tool',
                    'mountPath': destination, 'subPath': subpath, 'readOnly': True})
        grafana_clock_asset = os.getenv('GRAFANA_CLOCK_PLUGIN_ASSET', 'false').lower()
        if grafana_clock_asset not in ('true', 'false'):
            raise ValueError('GRAFANA_CLOCK_PLUGIN_ASSET 必须为 true 或 false')
        if grafana_clock_asset == 'true':
            if not grafana_claim or docker or cluster or distributed:
                raise ValueError('签名插件训练素材需要普通隔离工作区和GRAFANA_TOOL_PVC')
            container['volumeMounts'].append({'name': 'grafana-tool',
                'mountPath': '/opt/opsforge-training-assets/grafana-clock-panel-2.1.8.zip',
                'subPath': 'grafana-clock-panel-2.1.8.zip', 'readOnly': True})
        ceph_claim = os.getenv('CEPH_TOOL_PVC', '')
        if ceph_claim:
            if not re.fullmatch(r'[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?', ceph_claim):
                raise ValueError('CEPH_TOOL_PVC 必须是1至63位小写DNS标签')
            if docker or cluster or distributed:
                raise ValueError('Ceph工具仅适用于普通隔离工作区')
            spec['volumes'].append({'name': 'ceph-tool', 'persistentVolumeClaim': {
                'claimName': ceph_claim, 'readOnly': True}})
            for destination, subpath in (
                    ('/opt/opsforge-ceph', 'ceph-16.2.15'),
                    ('/usr/local/bin/crushtool', 'ceph-tool-launcher'),
                    ('/usr/local/bin/osdmaptool', 'ceph-tool-launcher'),
                    ('/usr/local/bin/monmaptool', 'ceph-monmap-launcher')):
                container['volumeMounts'].append({'name': 'ceph-tool',
                    'mountPath': destination, 'subPath': subpath, 'readOnly': True})
        ceph_cluster_claim = os.getenv('CEPH_CLUSTER_TOOL_PVC', '')
        if ceph_cluster_claim:
            if not re.fullmatch(r'[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?', ceph_cluster_claim):
                raise ValueError('CEPH_CLUSTER_TOOL_PVC 必须是1至63位小写DNS标签')
            if docker or cluster or distributed:
                raise ValueError('Ceph私有进程工具仅适用于普通隔离工作区')
            if ceph_claim:
                raise ValueError('两套Ceph工具目录不能同时挂载')
            spec['volumes'].append({'name': 'ceph-cluster-tool', 'persistentVolumeClaim': {
                'claimName': ceph_cluster_claim, 'readOnly': True}})
            pairs = [('/opt/opsforge-ceph', 'ceph-cluster-16.2.15')]
            pairs.extend(('/usr/local/bin/' + command, 'ceph-cluster-tool-launcher')
                         for command in ('ceph', 'ceph-mon', 'ceph-osd', 'ceph-authtool',
                                         'monmaptool', 'osdmaptool', 'crushtool', 'rados'))
            for destination, subpath in pairs:
                container['volumeMounts'].append({'name': 'ceph-cluster-tool',
                    'mountPath': destination, 'subPath': subpath, 'readOnly': True})
            container['env'].extend([
                {'name': 'LD_LIBRARY_PATH', 'value': '/opt/opsforge-ceph/usr/lib/x86_64-linux-gnu/ceph:/opt/opsforge-ceph/usr/lib/x86_64-linux-gnu:/opt/opsforge-ceph/lib/x86_64-linux-gnu'},
                {'name': 'PYTHONPATH', 'value': '/opt/opsforge-ceph/usr/lib/python3/dist-packages'}])
        rbd_claim = os.getenv('CEPH_RBD_TOOL_PVC', '')
        if rbd_claim:
            if not re.fullmatch(r'[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?', rbd_claim):
                raise ValueError('CEPH_RBD_TOOL_PVC 必须是1至63位小写DNS标签')
            if not ceph_cluster_claim or docker or cluster or distributed:
                raise ValueError('RBD只读附加工具需要普通隔离工作区和CEPH_CLUSTER_TOOL_PVC')
            spec['volumes'].append({'name': 'ceph-rbd-tool', 'persistentVolumeClaim': {
                'claimName': rbd_claim, 'readOnly': True}})
            for destination, subpath in (('/opt/opsforge-rbd', 'ceph-rbd-16.2.15'),
                                         ('/usr/local/bin/rbd', 'rbd-addon-launcher')):
                container['volumeMounts'].append({'name': 'ceph-rbd-tool',
                    'mountPath': destination, 'subPath': subpath, 'readOnly': True})
            for key, suffix in (
                    ('LD_LIBRARY_PATH', ':/opt/opsforge-rbd/usr/lib/x86_64-linux-gnu:/opt/opsforge-rbd/lib/x86_64-linux-gnu'),
                    ('PYTHONPATH', ':/opt/opsforge-rbd/usr/lib/python3/dist-packages')):
                next(variable for variable in container['env'] if variable['name'] == key)['value'] += suffix
        dbus_claim = os.getenv('DBUS_TOOL_PVC', '')
        if dbus_claim:
            if not re.fullmatch(r'[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?', dbus_claim):
                raise ValueError('DBUS_TOOL_PVC 必须是1至63位小写DNS标签')
            if docker or cluster or distributed:
                raise ValueError('私有D-Bus工具仅适用于普通隔离工作区')
            spec['volumes'].append({'name': 'dbus-tool', 'persistentVolumeClaim': {
                'claimName': dbus_claim, 'readOnly': True}})
            for destination, subpath in (
                    ('/opt/opsforge-dbus', 'dbus-tools'),
                    ('/usr/local/bin/dbus-daemon', 'dbus-tools/dbus-daemon')):
                container['volumeMounts'].append({'name': 'dbus-tool',
                    'mountPath': destination, 'subPath': subpath, 'readOnly': True})
            wheel = '/opt/opsforge-dbus/dbus_next.whl'
            python_path = next((variable for variable in container['env']
                                if variable['name'] == 'PYTHONPATH'), None)
            if python_path is None:
                container['env'].append({'name': 'PYTHONPATH', 'value': wheel})
            else:
                python_path['value'] += ':' + wheel
        cryptsetup_claim = os.getenv('CRYPTSETUP_TOOL_PVC', '')
        if cryptsetup_claim:
            if not re.fullmatch(r'[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?', cryptsetup_claim):
                raise ValueError('CRYPTSETUP_TOOL_PVC 必须是1至63位小写DNS标签')
            if docker or cluster or distributed:
                raise ValueError('普通文件LUKS工具仅适用于普通隔离工作区')
            spec['volumes'].append({'name': 'cryptsetup-tool', 'persistentVolumeClaim': {
                'claimName': cryptsetup_claim, 'readOnly': True}})
            for destination, subpath in (
                    ('/opt/opsforge-cryptsetup', 'cryptsetup-tools'),
                    ('/usr/local/bin/cryptsetup', 'cryptsetup-tools/cryptsetup')):
                container['volumeMounts'].append({'name': 'cryptsetup-tool',
                    'mountPath': destination, 'subPath': subpath, 'readOnly': True})
        private_api_budget = os.getenv('LAB_PRIVATE_API_BUDGET', 'false').lower()
        if private_api_budget not in ('true', 'false'):
            raise ValueError('LAB_PRIVATE_API_BUDGET 必须为 true 或 false')
        if private_api_budget == 'true':
            if docker or cluster or distributed:
                raise ValueError('私有API预算仅适用于普通隔离工作区')
            container['resources']['requests'].update({'cpu': '250m', 'memory': '256Mi'})
            container['resources']['limits'].update({'cpu': '2', 'memory': '2Gi'})
            container['env'].extend([{'name': 'GOMAXPROCS', 'value': '2'},
                                     {'name': 'GOMEMLIMIT', 'value': '384MiB'}])
        readonly_tmp = os.getenv('LAB_READ_ONLY_TMP', 'false').lower()
        if readonly_tmp not in ('true', 'false'):
            raise ValueError('LAB_READ_ONLY_TMP 必须为 true 或 false')
        if readonly_tmp == 'true':
            if docker or cluster or distributed:
                raise ValueError('只读/tmp训练仅适用于普通隔离工作区')
            next(mount for mount in container['volumeMounts'] if mount['mountPath'] == '/tmp')['readOnly'] = True
            container['env'].append({'name': 'TMPDIR', 'value': '/workspace'})
        return {"apiVersion": "v1", "kind": "Pod",
                "metadata": {"name": name, "namespace": self.distributed_namespace if distributed else self.docker_namespace if docker or cluster else self.namespace,
                             "labels": {"app.kubernetes.io/managed-by": "opsforge", "opsforge-role": "workspace"}}, "spec": spec}

    def start(self, docker=False, cluster=False, distributed=False):
        if not self.enabled:
            raise ValueError("当前未配置 Kubernetes 真实实验后端")
        with self.lock:
            name = "workspace-" + uuid.uuid4().hex[:10]
            manifest = self.manifest(name, docker, cluster, distributed)
            self.reconcile()
            if self.pending:
                raise ValueError("仍有工作区待清理，后台正在重试，请稍后创建")
            if self.current:
                raise ValueError("已有真实工作区，请先销毁它再创建；已保存代码不会被删除")
            api = self._api()
            self.current_namespace = manifest['metadata']['namespace']
            self.current = name
            self.last_used = time.time()
            try:
                api.create_namespaced_pod(self.current_namespace, manifest, _request_timeout=20)
                self._persist()
            except Exception:
                self.cancel_start(name)
                raise
            return {"pod": name, "phase": "Pending", "namespace": self.current_namespace}

    @contextmanager
    def prepared_start(self, docker, cluster, question, replace_pod=None):
        """Keep the previous workspace until candidate readiness and DB insertion succeed."""
        with self.lock:
            if self.current and self.current != replace_pod:
                raise ApiError('另一题已有真实工作区，请先保存并销毁该工作区', 409)
            if self.pending:
                raise ApiError('旧资源尚待清理，请稍后重试；当前工作区保留', 409)
            old = (self.current, self.current_namespace, self.last_used)
            self._staging = True
            self.current = None
            candidate = None
            try:
                from bank.hands_on import distributed_contract
                distributed = distributed_contract(question)
                candidate = self.start(docker, cluster, distributed)
                candidate['resource_profile'] = 'distributed' if distributed else 'standard'
                deadline = time.monotonic() + 45
                while True:
                    state = self.poll(candidate['pod'])
                    if state.get('ready'):
                        break
                    if state.get('phase') in ('Failed', 'Succeeded') or time.monotonic() >= deadline:
                        raise ApiError('新工作区未就绪，原工作区已保留：' + state.get('reason', state.get('phase', '超时')), 409)
                    if any(x in state.get('reason', '') for x in ('ImagePullBackOff','ErrImagePull','InvalidImageName','CreateContainerConfigError')):
                        raise ApiError('实验镜像或配置不可用，原工作区已保留：' + state['reason'], 409)
                    time.sleep(.5)
                if question['type'] == 'scenario':
                    result = self.setup_scenario(candidate['pod'], question)
                    if result['exit_code']:
                        raise ApiError('场景初始化失败，原工作区已保留：' + result['output'][-500:], 409)
                candidate.update(cwd='/workspace', initialized=True, phase='Ready')
                yield candidate
                self._staging = False
                self._persist()
            except BaseException:
                if self.current and self.current != old[0]:
                    self.cancel_start(self.current)
                self.current, self.current_namespace, self.last_used = old
                self._staging = False
                try:
                    self._persist()
                except Exception:
                    logging.exception('Could not persist restored workspace ownership')
                raise
            finally:
                self._staging = False
            if old[0]:
                item = {'name': old[0], 'namespace': old[1]}
                if item not in self.pending:
                    self.pending.append(item)
                try:
                    self._persist()
                    self._delete_pending(item)
                except Exception:
                    logging.exception('New workspace ready; old workspace cleanup queued')

    def poll(self, name):
        with self.lock:
            if name != self.current:
                raise ApiError("工作区不存在或已过期", 404)
            try:
                pod = self._api().read_namespaced_pod(name, self.current_namespace, _request_timeout=10)
            except Exception as exc:
                if getattr(exc, 'status', None) != 404:
                    raise
                self._forget_current()
                raise ApiError("工作区已不存在，请重新创建", 404) from exc
        conditions = [c for c in (pod.status.conditions or []) if c.type == "Ready"]
        reason = pod.status.reason or ""
        for s in pod.status.container_statuses or []:
            if s.state.waiting:
                reason = s.state.waiting.reason + ": " + (s.state.waiting.message or "")
        return {"phase": pod.status.phase, "ready": any(c.status == "True" for c in conditions), "reason": reason}

    def command(self, name, command, cwd="/workspace", timeout=20, stdin_data=""):
        with self.lock:
            if name != self.current or any(p['name'] == name for p in self.pending):
                raise ValueError("工作区不存在、正在清理或已过期")
            namespace = self.current_namespace
            self.last_used = time.time()
            self._persist()
        if len(command) > 24000:
            raise ValueError("命令过长")
        from kubernetes.stream import stream
        marker = '__OPS_' + uuid.uuid4().hex
        script = f"cd {shlex.quote(cwd)} || exit 1\n{command}\n_rc=$?\nprintf '\\n{marker}_CWD__%s\\n{marker}_RC__%s\\n' \"$PWD\" \"$_rc\"\nexit \"$_rc\""
        api = self._api()  # stream modifies the API client's transport; don't reuse it.
        ws = stream(api.connect_get_namespaced_pod_exec, name, namespace, container="workspace",
                    command=["timeout", "--kill-after=2", str(timeout), "bash", "-c", script], stderr=True, stdin=bool(stdin_data),
                    stdout=True, tty=False, _preload_content=False, _request_timeout=10)
        chunks, size, deadline = [], 0, time.monotonic() + timeout + 5
        try:
            for offset in range(0, len(stdin_data), 16384):
                ws.write_stdin(stdin_data[offset:offset + 16384])
            while ws.is_open() and time.monotonic() < deadline:
                ws.update(timeout=1)
                for reader in (ws.read_stdout, ws.read_stderr):
                    chunk = reader()
                    if chunk:
                        size += len(chunk)
                        if size > 200000:
                            chunks.append("\n[输出达到上限]\n")
                            break
                        chunks.append(chunk)
                if size > 200000:
                    break
            try:
                exit_code = getattr(ws, 'returncode', None) if not ws.is_open() else None
            except (TypeError, ValueError, KeyError, IndexError):
                # A dropped connection may have no Kubernetes status channel.
                exit_code = None
        finally:
            ws.close()
        output = "".join(chunks)
        import re
        match = re.search(r"\n" + marker + r"_CWD__(.*?)\n" + marker + r"_RC__(\d+)\n\Z", output, re.S)
        if exit_code is not None and size <= 200000:
            if match:
                return {"output": output[:match.start()], "cwd": match[1], "exit_code": exit_code}
            return {"output": output, "cwd": cwd, "exit_code": exit_code}
        return {"output": output + "\n[命令超时或输出截断，请检查工作区状态]", "cwd": cwd, "exit_code": 124}

    def write_files(self, name, files):
        validate_files(files)
        data = json.dumps(files, ensure_ascii=True)
        # Fixed-length stdin avoids command-line limits and does not need a remote EOF.
        from pathlib import Path
        receiver = Path(__file__).with_name('file_receiver.py').read_text(encoding='utf-8')
        command = "python3 -c " + shlex.quote(receiver) + " " + str(len(data))
        return self.command(name, command, timeout=60, stdin_data=data)

    def setup_scenario(self, name, question):
        kind = question["state"]["kind"]
        if kind == "permissions":
            return self.command(name, "printf 'TOKEN=training-only\\n' > /workspace/config.env; chmod 666 /workspace/config.env")
        if kind == "docker":
            port = question["state"]["port"]
            return self.command(name, f"docker info >/dev/null && (docker rm -f web >/dev/null 2>&1 || true); docker run -d --name web -p {port}:8080 nginx:alpine", timeout=90)
        if kind == "service":
            target = question["state"]["name"]
            labels = {"app": target, "opsforge-fixture": "true"}
            pod = self._api().read_namespaced_pod(name, self.current_namespace, _request_timeout=10)
            owners = [{'apiVersion':'v1','kind':'Pod','name':name,'uid':pod.metadata.uid}]
            deployment = {"apiVersion":"apps/v1","kind":"Deployment","metadata":{"name":target,"labels":labels},
                          "spec":{"replicas":1,"selector":{"matchLabels":{"app":target}},"template":{"metadata":{"labels":labels},"spec":{
                              "automountServiceAccountToken":False,"securityContext":{"runAsNonRoot":True,"runAsUser":1000,"seccompProfile":{"type":"RuntimeDefault"}},
                              "containers":[{"name":"echo","image":"hashicorp/http-echo:1.0.0","args":["-listen=:8080","-text=hello"],
                                             "ports":[{"containerPort":8080}],"resources":{"requests":{"cpu":"25m","memory":"16Mi"},"limits":{"cpu":"100m","memory":"64Mi"}},
                                             "securityContext":{"allowPrivilegeEscalation":False,"readOnlyRootFilesystem":True,"capabilities":{"drop":["ALL"]}},
                                             "readinessProbe":{"httpGet":{"path":"/","port":8080}}}]}}}}
            service = {"apiVersion":"v1","kind":"Service","metadata":{"name":target,"labels":labels},"spec":{"selector":{"app":"old-app"},"ports":[{"port":80,"targetPort":8080}]}}
            for obj in (deployment, service):
                obj['metadata']['ownerReferences'] = owners
            selector = os.getenv('LAB_NODE_SELECTOR', '')
            if selector:
                key, value = selector.split('=',1)
                deployment['spec']['template']['spec']['nodeSelector'] = {key:value}
            data = json.dumps({'apiVersion':'v1','kind':'List','items':[deployment,service]})
            # Never overwrite another workspace's fixture during candidate preparation.
            script = "import json,subprocess,sys\ndocs=json.loads(" + repr(data) + ")\n"
            script += "for obj in docs['items']:\n r=subprocess.run(['kubectl','get',obj['kind'],obj['metadata']['name'],'-o','json','--ignore-not-found'],capture_output=True,text=True)\n if r.returncode: sys.exit(r.stderr)\n if r.stdout.strip() and json.loads(r.stdout)['metadata'].get('ownerReferences')!=obj['metadata']['ownerReferences']: sys.exit('同名练习资源属于旧工作区，请先保存并销毁旧工作区')\n"
            script += "r=subprocess.run(['kubectl','apply','-f','-'],input=json.dumps(docs),text=True,capture_output=True)\nprint(r.stdout+r.stderr)\nsys.exit(r.returncode)"
            return self.command(name, 'python3 -c ' + shlex.quote(script), timeout=30)
        raise ValueError("此场景仅提供模拟故障；真实环境请选择基础实操、编程题或受支持场景")

    def check_scenario(self, name, question):
        kind, target = question["state"]["kind"], question["state"]["name"]
        if kind == "permissions":
            result = self.command(name, "stat -c %a /workspace/config.env")
            passed = result["exit_code"] == 0 and result["output"].strip() == "600"
            return {"passed": passed, "checks":[{"label":"真实文件权限为 600","passed":passed}],"method":"真实状态验收"}
        if kind == "service":
            result = self.command(name, f"kubectl get service {shlex.quote(target)} -o jsonpath='{{.spec.selector.app}}'; printf '\\n'; curl --fail --max-time 5 http://{target}")
            passed = result["exit_code"] == 0 and result["output"].splitlines()[0] == target
            return {"passed":passed,"checks":[{"label":"选择器正确且服务 HTTP 可访问","passed":passed}],"method":"真实状态验收"}
        if kind == "docker":
            port = question["state"]["port"]
            result = self.command(name, f"docker port web 80/tcp; curl --fail --max-time 5 http://localhost:{port}")
            passed = result["exit_code"] == 0 and f":{port}" in result["output"]
            return {"passed":passed,"checks":[{"label":"真实容器映射正确且 HTTP 可访问","passed":passed}],"method":"真实状态验收"}
        return {"passed":None,"method":"待自评","message":"本题真实环境结果需对照评分要点验收"}

    def stop(self, name):
        with self.lock:
            if name != self.current:
                return not any(p['name'] == name for p in self.pending)
            item = {"name": name, "namespace": self.current_namespace}
            if item not in self.pending:
                self.pending.append(item)
            self._persist()
            return self._delete_pending(item)

    def _persist(self):
        if self._staging:
            return
        self._save_state({"current": self.current, "namespace": self.current_namespace,
                          "last_used": self.last_used, "pending": self.pending})

    def _forget_current(self):
        # Only called while holding self.lock, after an authoritative Pod 404.
        self.pending = [item for item in self.pending
                        if (item['name'], item['namespace']) != (self.current, self.current_namespace)]
        self.current = None
        self.current_namespace = self.namespace
        self._persist()

    def _delete_pending(self, item):
        api = self._api()
        try:
            api.delete_namespaced_pod(item['name'], item['namespace'], grace_period_seconds=0, _request_timeout=10)
            # Accepted deletion is not confirmed deletion (finalizers may remain).
            api.read_namespaced_pod(item['name'], item['namespace'], _request_timeout=10)
            return False
        except Exception as exc:
            if getattr(exc, 'status', None) != 404:
                raise
        self.pending.remove(item)
        if self.current == item['name'] and self.current_namespace == item['namespace']:
            self.current = None
            self.current_namespace = self.namespace
        self._persist()
        return True

    def reconcile(self):
        with self.lock:
            if self._staging:
                return
            api = self._api()
            if self.current:
                try:
                    current = api.read_namespaced_pod(self.current, self.current_namespace, _request_timeout=10)
                except Exception as exc:
                    if getattr(exc, 'status', None) != 404:
                        raise  # Outages and permission failures must not discard ownership.
                    self._forget_current()
                else:
                    if getattr(getattr(current, 'status', None), 'phase', None) in ('Failed', 'Succeeded'):
                        item = {'name': self.current, 'namespace': self.current_namespace}
                        if item not in self.pending:
                            self.pending.append(item)
            if not self.current and not self.pending:
                self.current_namespace = self.namespace
            namespaces = {self.namespace, *(p['namespace'] for p in self.pending)}
            if self.current:
                namespaces.add(self.current_namespace)
            if self.docker or self.cluster:
                namespaces.add(self.docker_namespace)
            if self.distributed:
                namespaces.add(self.distributed_namespace)
            for namespace in namespaces:
                pods = api.list_namespaced_pod(namespace, label_selector="app.kubernetes.io/managed-by=opsforge,opsforge-role=workspace", _request_timeout=10)
                for pod in pods.items:
                    if pod.metadata.name == self.current and namespace == self.current_namespace:
                        continue
                    item = {"name": pod.metadata.name, "namespace": namespace}
                    if item not in self.pending:
                        self.pending.append(item)
            self._persist()
            for item in list(self.pending):
                try:
                    self._delete_pending(item)
                except Exception:
                    logging.exception("Workspace cleanup retry failed: %s/%s", item['namespace'], item['name'])

    def _reaper(self):
        while True:
            try:
                self.reconcile()
                if self.current and time.time() - self.last_used > 1200:
                    self.stop(self.current)
            except Exception:
                logging.exception("Workspace reconciliation failed; will retry")
            time.sleep(30)

    def cancel_start(self, name):
        """Compensate a failed create; preserve ownership even if storage fails."""
        with self.lock:
            item = {'name': name, 'namespace': self.current_namespace}
            if item not in self.pending:
                self.pending.append(item)
            try:
                self._persist()
            except Exception:
                logging.exception('Could not persist compensation; labelled Pod will be reconciled')
            try:
                self._delete_pending(item)
            except Exception:
                logging.exception('Creation compensation pending; reaper will retry')
