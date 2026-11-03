"""Read-only dedicated-node preflight; never labels nodes or switches contexts."""
import json
import subprocess
import sys
from deployment_config import load


def check(path):
    config, values = load(path)
    if config['lab_backend'] != 'kubernetes':
        return '场景模拟已启用；无需真实实验节点'
    selectors = [values['LAB_NODE_SELECTOR']]
    if values['ENABLE_DOCKER_LAB'] == 'true' or values.get('ENABLE_CLUSTER_LAB') == 'true':
        selectors.append(values['DOCKER_NODE_SELECTOR'])
    if values.get('ENABLE_DISTRIBUTED_LAB') == 'true':
        selectors.append(values['DISTRIBUTED_NODE_SELECTOR'])
    for selector in dict.fromkeys(selectors):
        result = subprocess.run(['kubectl','get','nodes','-l',selector,'-o','json'],
                                capture_output=True,text=True,check=True,timeout=30)
        nodes = json.loads(result.stdout)['items']
        ready = [n for n in nodes if not n.get('spec',{}).get('unschedulable')
                 and not any(t.get('effect') in ('NoSchedule','NoExecute') for t in n.get('spec',{}).get('taints',[]))
                 and any(c.get('type')=='Ready' and c.get('status')=='True' for c in n.get('status',{}).get('conditions',[]))]
        if not ready:
            raise ValueError('未找到匹配标签且 Ready、可调度的专用实验节点；未执行部署')
    return '专用实验节点预检通过' + ('（含 Docker 专用节点）' if values['ENABLE_DOCKER_LAB'] == 'true' else '') + ('（含独立 K3s 专用节点；仍需核对特权侧车与3CPU/约3Gi剩余容量）' if values.get('ENABLE_CLUSTER_LAB') == 'true' else '') + ('（含分布式服务节点；仍需核对5Gi/2CPU剩余容量）' if values.get('ENABLE_DISTRIBUTED_LAB') == 'true' else '') + '；请确认 CNI 支持 NetworkPolicy'


if __name__=='__main__':
    try:
        print(check(sys.argv[1]))
    except (ValueError,OSError,IndexError,KeyError,subprocess.SubprocessError):
        print('实验节点预检失败，请核对 lab_node_selector、节点状态及当前只读权限；未执行部署',file=sys.stderr)
        sys.exit(2)
