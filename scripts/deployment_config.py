"""Plain JSON configuration for external PostgreSQL; never evaluate configuration."""
import ipaddress
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote, urlencode

DOMAINS = ('auth', 'bank', 'learning', 'exams', 'labs')
DEFAULT_K3S_IMAGE = 'rancher/k3s@sha256:5e0707cfd1239b358ef73f3254bc3eadc027dd30cd5ec6ca41e29e47652a1b8c'

def load(path):
    config = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    optional = {'lab_node_selector', 'enable_docker_lab', 'docker_node_selector',
                'enable_distributed_lab', 'distributed_node_selector',
                'enable_cluster_lab', 'k3s_image', 'k3s_preload_images', 'node_lab_image'}
    if not isinstance(config, dict) or set(config)-optional != {'postgres','platform_password','service_token','cookie_secure','lab_backend','node_port'}:
        raise ValueError('配置字段不完整或含未知字段，请使用 deploy/config.json 模板')
    pg = config['postgres']
    if not isinstance(pg, dict) or set(pg) != {'host','port','sslmode','databases'}:
        raise ValueError('postgres 配置需要 host、port、sslmode、databases')
    host = pg['host']
    if not isinstance(host, str) or not host or len(host) > 253:
        raise ValueError('请填写外部 PostgreSQL host')
    try:
        address = ipaddress.ip_address(host)
        if address.is_loopback or address.is_unspecified or address.is_multicast:
            raise ValueError('PostgreSQL 必须使用 Pod 可访问的外部地址')
    except ValueError:
        if ':' in host or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', host) or host.lower() in ('localhost','opsforge-postgres'):
            raise ValueError('PostgreSQL host 格式错误或仍指向本地数据库') from None
        # A numeric IP must not bypass the external-address validation above.
        if re.fullmatch(r'[0-9.]+', host):
            address = ipaddress.ip_address(host)
            if address.is_loopback or address.is_unspecified or address.is_multicast:
                raise ValueError('PostgreSQL 必须使用 Pod 可访问的外部地址')
    if type(pg['port']) is not int or not 1 <= pg['port'] <= 65535:
        raise ValueError('postgres.port 必须为 1–65535 整数')
    if pg['sslmode'] not in ('disable','prefer','require'):
        raise ValueError('postgres.sslmode 支持 disable、prefer、require')
    if not isinstance(pg['databases'], dict) or set(pg['databases']) != set(DOMAINS):
        raise ValueError('需要填写全部五个业务数据库')
    values, names = {}, set()
    for domain in DOMAINS:
        item = pg['databases'][domain]
        if not isinstance(item, dict) or set(item) != {'name','user','password'}:
            raise ValueError(domain + ' 数据库需要 name、user、password')
        for field in ('name','user'):
            if not isinstance(item[field], str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]{0,62}', item[field]):
                raise ValueError(domain + '.' + field + ' 请填写有效的数据库名/账号')
        if item['name'] in names:
            raise ValueError('五个业务模块必须使用不同数据库')
        names.add(item['name'])
        password = item['password']
        if not isinstance(password, str) or not password or '\x00' in password:
            raise ValueError(domain + ' 数据库密码不能为空或含空字符')
        authority = '[' + host + ']' if ':' in host else host
        values[domain.upper() + '_DATABASE_URL'] = ('postgresql://' + quote(item['user'], safe='') + ':' + quote(password, safe='') + '@' + authority + ':' + str(pg['port']) + '/' + quote(item['name'], safe='') + '?' + urlencode({'sslmode':pg['sslmode'], 'connect_timeout':10}))
    for field, minimum in (('platform_password',12),('service_token',32)):
        value = config[field]
        if not isinstance(value,str) or len(value) < minimum or any(ord(c)<32 for c in value):
            raise ValueError(field + ' 请填写至少 ' + str(minimum) + ' 字符的单行文本')
    if type(config['cookie_secure']) is not bool or config['lab_backend'] not in ('simulation','kubernetes'):
        raise ValueError('cookie_secure 必须为布尔值；lab_backend 为 simulation 或 kubernetes')
    selector = config.get('lab_node_selector','')
    if not isinstance(selector,str) or (selector and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9./_-]*=[A-Za-z0-9][A-Za-z0-9_.-]*',selector)):
        raise ValueError('lab_node_selector 格式为节点标签键=值')
    if config['lab_backend']=='kubernetes' and not selector:
        raise ValueError('真实实验必须配置专用实验节点 lab_node_selector')
    docker_enabled = config.get('enable_docker_lab', False)
    docker_selector = config.get('docker_node_selector', '')
    if type(docker_enabled) is not bool:
        raise ValueError('enable_docker_lab 必须为布尔值，默认 false')
    if not isinstance(docker_selector, str) or (docker_selector and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9./_-]*=[A-Za-z0-9][A-Za-z0-9_.-]*', docker_selector)):
        raise ValueError('docker_node_selector 格式为专用节点标签键=值')
    if docker_enabled and (config['lab_backend'] != 'kubernetes' or not docker_selector):
        raise ValueError('Docker 实验必须显式启用 Kubernetes 并配置 docker_node_selector 专用节点')
    cluster_enabled = config.get('enable_cluster_lab', False)
    preload_images = config.get('k3s_preload_images', False)
    if type(cluster_enabled) is not bool or type(preload_images) is not bool:
        raise ValueError('enable_cluster_lab 和 k3s_preload_images 必须为布尔值，默认 false')
    if cluster_enabled and (config['lab_backend'] != 'kubernetes' or not docker_selector):
        raise ValueError('独立 K3s 实验必须显式启用 Kubernetes 并配置 docker_node_selector 专用节点')
    if preload_images and not cluster_enabled:
        raise ValueError('K3s 镜像预缓存必须同时显式启用独立集群实验')
    k3s_image = config.get('k3s_image', DEFAULT_K3S_IMAGE)
    if not isinstance(k3s_image, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[a-f0-9]{64}', k3s_image):
        raise ValueError('k3s_image 必须为已核验、固定 sha256 的镜像引用')
    if preload_images and k3s_image == DEFAULT_K3S_IMAGE:
        raise ValueError('启用预缓存须提供含 opsforge-k3s-bootstrap 与镜像归档的独立 K3s 镜像摘要')
    node_image = config.get('node_lab_image', 'busybox:1.36.1')
    if node_image not in ('busybox:1.36.1', 'busybox@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662'):
        raise ValueError('node_lab_image 必须使用已审校的 BusyBox 1.36.1 缓存引用')
    distributed_enabled = config.get('enable_distributed_lab', False)
    distributed_selector = config.get('distributed_node_selector', '')
    if type(distributed_enabled) is not bool:
        raise ValueError('enable_distributed_lab 必须为布尔值，默认 false')
    if not isinstance(distributed_selector, str) or (distributed_selector and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9./_-]*=[A-Za-z0-9][A-Za-z0-9_.-]*', distributed_selector)):
        raise ValueError('distributed_node_selector 格式为专用节点标签键=值')
    if distributed_enabled and (config['lab_backend'] != 'kubernetes' or not distributed_selector):
        raise ValueError('分布式服务实验必须显式启用 Kubernetes 并配置 distributed_node_selector')
    if type(config['node_port']) is not int or not 30000 <= config['node_port'] <= 32767:
        raise ValueError('node_port 必须为 30000–32767 整数')
    values.update(OPSFORGE_PASSWORD=config['platform_password'], SERVICE_SECRET=config['service_token'],
                  COOKIE_SECURE=str(config['cookie_secure']).lower(), LAB_BACKEND=config['lab_backend'], LAB_NODE_SELECTOR=selector,
                  ENABLE_DOCKER_LAB=str(docker_enabled).lower(), DOCKER_NODE_SELECTOR=docker_selector,
                  ENABLE_CLUSTER_LAB=str(cluster_enabled).lower(), K3S_IMAGE=k3s_image,
                  K3S_PRELOAD_IMAGES=str(preload_images).lower(), NODE_LAB_IMAGE=node_image,
                  ENABLE_DISTRIBUTED_LAB=str(distributed_enabled).lower(), DISTRIBUTED_NODE_SELECTOR=distributed_selector)
    return config, values

if __name__ == '__main__':
    try:
        load(sys.argv[1])
        print('明文配置校验通过（未连接数据库）')
    except (ValueError, OSError, IndexError, KeyError, TypeError):
        print('配置校验失败：请核对 JSON 格式、外部数据库、五个账号密码、平台密码和服务认证值。', file=sys.stderr)
        sys.exit(2)
