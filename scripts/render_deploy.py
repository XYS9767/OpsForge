"""Validate immutable image references and explicit Kubernetes API egress."""
import ipaddress
import json
from pathlib import Path
import re
import sys
import hashlib
from deployment_config import load


def render(template, release, discovery, registry, configuration=None):
    output = template
    if configuration is not None and (configuration[1].get('ENABLE_DOCKER_LAB') == 'true'
                                      or configuration[1].get('ENABLE_CLUSTER_LAB') == 'true'):
        optional = Path(__file__).resolve().parents[1] / 'deploy/docker-lab.optional.yaml'
        output += '\n---\n' + optional.read_text(encoding='utf-8')
    if configuration is not None and configuration[1].get('ENABLE_DISTRIBUTED_LAB') == 'true':
        optional = Path(__file__).resolve().parents[1] / 'deploy/distributed-lab.optional.yaml'
        output += '\n---\n' + optional.read_text(encoding='utf-8')
    for part in ('backend', 'frontend', 'lab'):
        image = release['images'][part]
        if not re.fullmatch(re.escape(registry.rstrip('/') + '/opsforge-' + part) + r'@sha256:[a-f0-9]{64}', image):
            raise ValueError('Missing or invalid immutable image digest: ' + part)
        output = output.replace('IMAGE_' + part.upper(), image)
    peers = set()
    for item in discovery.get('items', [discovery]):
        if item.get('kind') == 'Endpoints':
            for subset in item.get('subsets', []):
                for address in subset.get('addresses', []):
                    for port in subset.get('ports', []):
                        if port.get('protocol', 'TCP') == 'TCP':
                            peers.add((str(ipaddress.ip_address(address['ip'])), int(port['port'])))
        elif item.get('kind') == 'Service':
            for address in item['spec'].get('clusterIPs', [item['spec']['clusterIP']]):
                for port in item['spec']['ports']:
                    if port.get('protocol', 'TCP') == 'TCP':
                        peers.add((str(ipaddress.ip_address(address)), int(port['port'])))
    if not peers or any(not 1 <= port <= 65535 for _, port in peers):
        raise ValueError('Discover Kubernetes API endpoints before deployment')
    rules = []
    for address, port in sorted(peers):
        cidr = str(ipaddress.ip_network(address + ('/128' if ':' in address else '/32')))
        rules.append('    - to:\n        - ipBlock: {cidr: "' + cidr + '"}\n      ports:\n        - {protocol: TCP, port: ' + str(port) + '}')
    output = output.replace('    # API_SERVER_EGRESS', '\n'.join(rules))
    if configuration is not None:
        config, values = configuration
        fingerprint = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
        output = output.replace('CONFIG_FINGERPRINT', fingerprint).replace('EXTERNAL_NODE_PORT', str(config['node_port']))
        cm = {'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'opsforge-config','namespace':'opsforge'},'data':values}
        return json.dumps(cm, ensure_ascii=False, indent=2) + '\n---\n' + output
    if 'CONFIG_FINGERPRINT' in output:
        raise ValueError('External deployment configuration is required')
    return output


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    try:
        print(render((root/'deploy/k8s.yaml').read_text(encoding='utf-8'),
                     json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')),
                     json.loads(Path(sys.argv[2]).read_text(encoding='utf-8')), sys.argv[3], load(sys.argv[4])))
    except (ValueError, OSError, KeyError, IndexError, TypeError):
        print('部署清单生成失败，请核对发布清单、API 地址与明文配置文件。', file=sys.stderr)
        sys.exit(2)
