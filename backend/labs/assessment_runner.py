"""Run reviewed checks inside the disposable workspace, never on the API host."""
import json
import hashlib
import ctypes
import importlib.util
import os
import platform
from pathlib import Path
import re
import secrets
import signal
import shutil
import subprocess
import sys
import tempfile
import threading


PRIVATE_NODE_CAPABILITIES_PROBE = '"""Real private-node fixture; never starts or substitutes an API-only mock."""\nimport base64\nimport hashlib\nimport json\nimport os\nfrom pathlib import Path\nimport secrets\nimport ssl\nimport subprocess\nimport tempfile\nimport time\nimport urllib.error\nimport urllib.parse\nimport urllib.request\n\n\ndef token(prefix=\'x\'):\n    return prefix+\'-\'+secrets.token_hex(5)\n\n\nclass NodeSession:\n    """Requires explicit, disposable, loopback K3s workspace credentials."""\n    def __init__(self):\n        supplied=os.environ.get(\'KUBECONFIG\',\'\')\n        if not supplied or os.pathsep in supplied:\n            raise RuntimeError(\'Explicit single-file private KUBECONFIG is required; no default fallback\')\n        self.original_config=Path(supplied).resolve()\n        if not self.original_config.is_file():\n            raise RuntimeError(\'Private cluster kubeconfig is unavailable\')\n        self.original_hash=hashlib.sha256(self.original_config.read_bytes()).hexdigest()\n        self.temp=tempfile.TemporaryDirectory(prefix=\'opsforge-node-fixture-\')\n        self.root=Path(self.temp.name);self.root.chmod(0o700)\n        self.ns=token(\'opsforge-node\');self.ns_uid=None;self.trace=[]\n        self.image=os.environ.get(\'OPSF_NODE_IMAGE\',\'\')\n        if not self.image:\n            self.temp.cleanup()\n            raise RuntimeError(\'OPSF_NODE_IMAGE must name the pre-cached native executable fixture image\')\n        proc=subprocess.run([\'kubectl\',\'--kubeconfig\',str(self.original_config),\'config\',\'view\',\'--raw\',\'--flatten\',\'-o\',\'json\'],capture_output=True,text=True,timeout=10)\n        if proc.returncode:\n            self.temp.cleanup();raise RuntimeError(\'Cannot read private kubeconfig: \'+proc.stderr[:500])\n        cfg=json.loads(proc.stdout);self.context=cfg[\'current-context\']\n        ctx=next(x[\'context\'] for x in cfg[\'contexts\'] if x[\'name\']==self.context)\n        cluster=next(x[\'cluster\'] for x in cfg[\'clusters\'] if x[\'name\']==ctx[\'cluster\'])\n        user=next(x[\'user\'] for x in cfg[\'users\'] if x[\'name\']==ctx[\'user\'])\n        self.server=cluster[\'server\'].rstrip(\'/\')\n        url=urllib.parse.urlsplit(self.server)\n        if url.scheme!=\'https\' or url.hostname not in (\'127.0.0.1\',\'localhost\',\'::1\'):\n            self.temp.cleanup();raise RuntimeError(\'This fixture requires a private loopback cluster, not an external/shared endpoint\')\n        if cluster.get(\'insecure-skip-tls-verify\'):\n            self.temp.cleanup();raise RuntimeError(\'Native fixture requires verified TLS\')\n        self.tls=ssl.create_default_context(cadata=base64.b64decode(cluster[\'certificate-authority-data\']).decode())\n        if \'client-certificate-data\' in user and \'client-key-data\' in user:\n            cert=self.root/\'client.crt\';key=self.root/\'client.key\'\n            cert.write_bytes(base64.b64decode(user[\'client-certificate-data\']))\n            key.write_bytes(base64.b64decode(user[\'client-key-data\']));key.chmod(0o600)\n            self.tls.load_cert_chain(str(cert),str(key))\n        self.bearer=user.get(\'token\')\n        if \'tokenFile\' in user:\n            self.bearer=Path(user[\'tokenFile\']).read_text().strip()\n        self.config=self.root/\'kubeconfig.json\';self.config.write_text(json.dumps(cfg));self.config.chmod(0o600)\n        self.initial_context=ctx\n\n    def request(self,method,path,value=None,ctype=\'application/json\'):\n        assert path.startswith(\'/\') and not path.startswith(\'//\')\n        headers={\'Content-Type\':ctype}\n        if self.bearer:headers[\'Authorization\']=\'Bearer \'+self.bearer\n        data=None if value is None else json.dumps(value).encode()\n        request=urllib.request.Request(self.server+path,data=data,headers=headers,method=method)\n        try:\n            with urllib.request.urlopen(request,context=self.tls,timeout=10) as response:\n                raw=response.read();code=response.status\n        except urllib.error.HTTPError as error:\n            code=error.code;raw=error.read()\n        try:result=json.loads(raw)\n        except (ValueError,UnicodeDecodeError):result=raw.decode(errors=\'replace\')\n        return code,result\n\n    def get(self,path):\n        code,result=self.request(\'GET\',path);assert code==200,(code,result)\n        return result\n\n    def api(self,method,path,value=None,ctype=\'application/json\'):\n        # Learner callback has no cluster-scope write capability.\n        clean=urllib.parse.urlsplit(path).path\n        allowed=(\'/api/v1/namespaces/\'+self.ns+\'/\', \'/apis/apps/v1/namespaces/\'+self.ns+\'/\', \'/apis/networking.k8s.io/v1/namespaces/\'+self.ns+\'/\')\n        if not clean.startswith(allowed) or \'..\' in clean or \'%\' in clean:\n            raise AssertionError(\'Learner operation must stay inside the private exercise namespace\')\n        result=self.request(method,path,value,ctype)\n        self.trace.append({\'method\':method,\'path\':path,\'status\':result[0]})\n        return result\n\n    def run(self,args):\n        assert isinstance(args,list) and args and all(isinstance(x,str) for x in args)\n        assert args[0] in (\'get\',\'describe\',\'logs\',\'exec\',\'rollout\',\'patch\',\'wait\')\n        assert not any(x in (\'--all-namespaces\',\'-A\',\'--kubeconfig\',\'--context\',\'--namespace\',\'-n\',\'--server\',\'--token\') or x.startswith((\'--kubeconfig=\',\'--context=\',\'--namespace=\',\'--server=\',\'--token=\')) for x in args)\n        command=[\'kubectl\',\'--kubeconfig\',str(self.config),\'--context\',self.context,\'-n\',self.ns]+args\n        proc=subprocess.run(command,capture_output=True,text=True,timeout=15)\n        self.trace.append({\'args\':args,\'status\':proc.returncode})\n        return proc.returncode,proc.stdout,proc.stderr\n\n    def wait(self,predicate,seconds=30,description=\'real native state\'):\n        deadline=time.monotonic()+seconds\n        while time.monotonic()<deadline:\n            result=predicate()\n            if result:return result\n            time.sleep(.25)\n        raise RuntimeError(\'Native cluster did not reach \'+description)\n\n    def path(self,resource,name=None,group=\'/api/v1\'):\n        return f\'{group}/namespaces/{self.ns}/{resource}\'+(\'/\'+name if name else \'\')\n\n    def create(self,resource,obj,group=\'/api/v1\'):\n        code,result=self.request(\'POST\',self.path(resource,group=group),obj)\n        assert code==201,(code,result)\n        return result\n\n    def pod(self,spec=None,name=None,**metadata):\n        base={\'automountServiceAccountToken\':False,\'terminationGracePeriodSeconds\':0,\'nodeSelector\':{\'hw\':\'compute\'},\n              \'containers\':[{\'name\':\'main\',\'image\':self.image,\'imagePullPolicy\':\'Never\',\'command\':[\'sh\',\'-c\',\'sleep 3600\'],\n                             \'resources\':{\'requests\':{\'cpu\':\'5m\',\'memory\':\'4Mi\'},\'limits\':{\'cpu\':\'50m\',\'memory\':\'32Mi\'}}}]}\n        if spec:\n            base.update(spec)\n            base[\'nodeSelector\']={\'hw\':\'compute\',**spec.get(\'nodeSelector\',{})}\n        return self.create(\'pods\',{\'apiVersion\':\'v1\',\'kind\':\'Pod\',\'metadata\':{\'name\':name or token(\'pod\'),**metadata},\'spec\':base})\n\n    def ready_pod(self,name,seconds=30):\n        def ready():\n            obj=self.get(self.path(\'pods\',name))\n            return obj if any(c[\'type\']==\'Ready\' and c[\'status\']==\'True\' for c in obj.get(\'status\',{}).get(\'conditions\',[])) else False\n        return self.wait(ready,seconds,\'kubelet Pod Ready\')\n\n    def __enter__(self):\n        try:\n            self.version=self.get(\'/version\')[\'gitVersion\']\n            if not self.version.startswith(\'v1.34.1\'):\n                raise RuntimeError(\'Native node contracts require the fixed Kubernetes v1.34.1 workspace\')\n            self.nodes=self.get(\'/api/v1/nodes\')[\'items\']\n            self.node=next((n for n in self.nodes if n[\'metadata\'].get(\'labels\',{}).get(\'hw\')==\'compute\' and any(c[\'type\']==\'Ready\' and c[\'status\']==\'True\' for c in n.get(\'status\',{}).get(\'conditions\',[]))),None)\n            if not self.node:raise RuntimeError(\'No actual Ready kubelet node in private cluster\')\n            code,ns=self.request(\'POST\',\'/api/v1/namespaces\',{\'apiVersion\':\'v1\',\'kind\':\'Namespace\',\'metadata\':{\'name\':self.ns,\'labels\':{\'opsforge-owned\':\'node-contract\'}}})\n            assert code==201,(code,ns);self.ns_uid=ns[\'metadata\'][\'uid\']\n            self.wait(lambda:self.request(\'GET\',self.path(\'serviceaccounts\',\'default\'))[0]==200,5,\'native default service account\')\n            self.base=self.create(\'configmaps\',{\'apiVersion\':\'v1\',\'kind\':\'ConfigMap\',\'metadata\':{\'name\':token(\'baseline\')},\'data\':{\'preserve\':token(\'payload\')}})\n            self.base_path=self.path(\'configmaps\',self.base[\'metadata\'][\'name\'])\n            nonce=token(\'native\')\n            probe=self.pod({\'containers\':[{\'name\':\'main\',\'image\':self.image,\'imagePullPolicy\':\'Never\',\'command\':[\'sh\',\'-c\',\'echo \'+nonce+\'; sleep 3600\'],\n                \'resources\':{\'requests\':{\'cpu\':\'5m\',\'memory\':\'4Mi\'},\'limits\':{\'cpu\':\'50m\',\'memory\':\'32Mi\'}}}]})\n            self.ready_pod(probe[\'metadata\'][\'name\'])\n            code,out,err=self.run([\'logs\',probe[\'metadata\'][\'name\'],\'-c\',\'main\']);assert code==0 and nonce in out,(code,out,err)\n            code,out,err=self.run([\'exec\',probe[\'metadata\'][\'name\'],\'-c\',\'main\',\'--\',\'sh\',\'-c\',\'printf \'+nonce]);assert code==0 and out==nonce,(code,out,err)\n            self.trace=[]\n            print(\'NATIVE_NODE_READY:\'+json.dumps({\'server_version\':self.version,\'kubelet_version\':self.node[\'status\'][\'nodeInfo\'][\'kubeletVersion\'],\n                \'container_runtime\':self.node[\'status\'][\'nodeInfo\'][\'containerRuntimeVersion\'],\'native_pod_uid\':probe[\'metadata\'][\'uid\'],\'image_id\':self.get(self.path(\'pods\',probe[\'metadata\'][\'name\']))[\'status\'][\'containerStatuses\'][0][\'imageID\']},sort_keys=True),flush=True)\n            # Preserve actual readiness evidence, then free the native probe slot.\n            code,obj=self.request(\'DELETE\',self.path(\'pods\',probe[\'metadata\'][\'name\']),{\'apiVersion\':\'v1\',\'kind\':\'DeleteOptions\',\'preconditions\':{\'uid\':probe[\'metadata\'][\'uid\']},\'gracePeriodSeconds\':0})\n            assert code in (200,202),(code,obj)\n            self.wait(lambda:self.request(\'GET\',self.path(\'pods\',probe[\'metadata\'][\'name\']))[0]==404,8,\'native probe removal before exercise workloads\')\n            return self\n        except BaseException:\n            self.close();raise\n\n    def close(self):\n        try:\n            if self.ns_uid:\n                self.request(\'DELETE\',\'/api/v1/namespaces/\'+self.ns,{\'apiVersion\':\'v1\',\'kind\':\'DeleteOptions\',\'preconditions\':{\'uid\':self.ns_uid}})\n        finally:self.temp.cleanup()\n\n    def __exit__(self,typ,value,tb):\n        try:\n            if typ is None:\n                assert self.get(self.base_path)==self.base,\'Original data or original namespace access regressed\'\n                assert hashlib.sha256(self.original_config.read_bytes()).hexdigest()==self.original_hash,\'Original explicit kubeconfig changed\'\n                print(\'ORIGINAL_ACCESS_AND_DATA_RETAINED\',flush=True)\n        finally:self.close()\n\n\nimport base64\n\nimport copy\n\nimport importlib.util\n\nimport json\n\nimport ipaddress\n\nfrom pathlib import Path\n\nimport secrets\n\nimport struct\n\nimport time\n\nimport urllib.parse\n\nimport urllib.request\n\ndef container(s,name=\'main\',script=\'sleep 3600\',**extra):\n    return {\'name\':name,\'image\':s.image,\'imagePullPolicy\':\'Never\',\'command\':[\'sh\',\'-c\',script],\n            \'resources\':{\'requests\':{\'cpu\':\'5m\',\'memory\':\'4Mi\'},\'limits\':{\'cpu\':\'50m\',\'memory\':\'32Mi\'}},**extra}\n\ndef execution(s,pod,command):\n    return s.run([\'exec\',pod,\'-c\',\'main\',\'--\']+command)\n\ndef server(s,role,port=8080):\n    payload=token(\'http\');key=token(\'path\')\n    p=s.pod({\'containers\':[container(s,script=f\'mkdir -p /web; printf %s {payload} > /web/{key}; httpd -f -p {port} -h /web\')]},labels={\'role\':role})\n    p=s.ready_pod(p[\'metadata\'][\'name\'])\n    return {\'pod\':p,\'name\':p[\'metadata\'][\'name\'],\'url\':f\'http://\'+p[\'status\'][\'podIP\']+f\':{port}/{key}\',\'payload\':payload,\'port\':port}\n\ndef fetch(s,source,target,url=None):\n    code,out,err=execution(s,source[\'name\'],[\'wget\',\'-T\',\'1\',\'-qO-\',url or target[\'url\']])\n    return code==0 and out==target[\'payload\']\n\ndef np(s,name,selector,types,**rules):\n    obj={\'apiVersion\':\'networking.k8s.io/v1\',\'kind\':\'NetworkPolicy\',\'metadata\':{\'name\':name},\'spec\':{\'podSelector\':{\'matchLabels\':selector},\'policyTypes\':types,**rules}}\n    return s.create(\'networkpolicies\',obj,\'/apis/networking.k8s.io/v1\')\n\ndef network_capability_control(s):\n    """Actual data-plane deny is bracketed by allowed and recovery controls."""\n    target,allowed,denied=[server(s,token(role)) for role in (\'target\',\'allowed\',\'denied\')]\n    all_servers=[target,allowed,denied]\n    assert all(fetch(s,a,b) for a in all_servers for b in all_servers if a is not b),\'Baseline native Pod HTTP must work bidirectionally\'\n    rule=np(s,token(\'preflight\'),target[\'pod\'][\'metadata\'][\'labels\'],[\'Ingress\'],ingress=[{\'from\':[{\'podSelector\':{\'matchLabels\':allowed[\'pod\'][\'metadata\'][\'labels\']}}],\'ports\':[{\'protocol\':\'TCP\',\'port\':8080}]}])\n    def enforced():\n        return not fetch(s,denied,target) and fetch(s,allowed,target) and fetch(s,denied,allowed) and fetch(s,target,denied)\n    s.wait(enforced,15,\'real NetworkPolicy data-plane enforcement with live allowed controls\')\n    path=s.path(\'networkpolicies\',rule[\'metadata\'][\'name\'],\'/apis/networking.k8s.io/v1\')\n    code,obj=s.request(\'DELETE\',path,{\'apiVersion\':\'v1\',\'kind\':\'DeleteOptions\',\'preconditions\':{\'uid\':rule[\'metadata\'][\'uid\']}});assert code in (200,202),(code,obj)\n    s.wait(lambda:fetch(s,denied,target) and fetch(s,target,denied),10,\'NetworkPolicy removal restores only the preflight path\')\n    print(\'NATIVE_NETWORK_POLICY_CONTROL_READY\',flush=True)\n    return target,allowed,denied\n\ndef service(s,target):\n    obj=s.create(\'services\',{\'apiVersion\':\'v1\',\'kind\':\'Service\',\'metadata\':{\'name\':token(\'query\')},\n        \'spec\':{\'selector\':target[\'pod\'][\'metadata\'][\'labels\'],\'ports\':[{\'name\':\'http\',\'port\':8080,\'targetPort\':8080}]}})\n    return obj\n\ndef dns_udp(s,source,svc):\n    fqdn=svc[\'metadata\'][\'name\']+\'.\'+s.ns+\'.svc.cluster.local.\'\n    code,out,err=execution(s,source[\'name\'],[\'nslookup\',\'-type=A\',\'-timeout=1\',fqdn])\n    return code==0 and svc[\'spec\'][\'clusterIP\'] in out\n\ndef dns_tcp(s,source,svc,dns_ip):\n    dns_ip=str(ipaddress.ip_address(dns_ip))\n    name=svc[\'metadata\'][\'name\']+\'.\'+s.ns+\'.svc.cluster.local\'\n    identity=secrets.randbelow(65536)\n    packet=struct.pack(\'!HHHHHH\',identity,0x100,1,0,0,0)+b\'\'.join(bytes([len(label)])+label.encode() for label in name.split(\'.\'))+b\'\\x00\\x00\\x01\\x00\\x01\'\n    framed=struct.pack(\'!H\',len(packet))+packet\n    octal=\'\'.join(\'\\\\0%03o\'%value for value in framed)\n    script="printf \'%b\' \'"+octal+"\' | nc -w 2 "+dns_ip+" 53 | base64"\n    code,out,err=execution(s,source[\'name\'],[\'sh\',\'-c\',script])\n    if code:return False\n    try:raw=base64.b64decode(out)\n    except ValueError:return False\n    if len(raw)<14:return False\n    length=struct.unpack(\'!H\',raw[:2])[0];message=raw[2:]\n    if len(message)!=length:return False\n    actual,flags,queries,answers,_,_=struct.unpack(\'!HHHHHH\',message[:12])\n    return actual==identity and flags&0x8000 and flags&15==0 and answers>0 and ipaddress.ip_address(svc[\'spec\'][\'clusterIP\']).packed in message\n\nimport sys\n\ndef network_probe():\n    with NodeSession() as s:\n        target,client,forbidden=network_capability_control(s)\n        dns=s.get(\'/api/v1/namespaces/kube-system/services/kube-dns\')\n        before=service(s,target)\n        s.wait(lambda:dns_udp(s,client,before) and dns_tcp(s,client,before,dns[\'spec\'][\'clusterIP\']),10,\'native CoreDNS UDP and TCP capability\')\n        policy=np(s,token(\'capability-egress\'),client[\'pod\'][\'metadata\'][\'labels\'],[\'Egress\'],\n            egress=[{\'to\':[{\'podSelector\':{\'matchLabels\':target[\'pod\'][\'metadata\'][\'labels\']}}],\'ports\':[{\'protocol\':\'TCP\',\'port\':8080}]}])\n        blocked=service(s,target)\n        s.wait(lambda:fetch(s,client,target) and not fetch(s,client,forbidden) and not dns_udp(s,client,blocked) and not dns_tcp(s,client,blocked,dns[\'spec\'][\'clusterIP\']),10,\'native egress deny with allowed dependency still live\')\n        code,obj=s.request(\'DELETE\',s.path(\'networkpolicies\',policy[\'metadata\'][\'name\'],\'/apis/networking.k8s.io/v1\'),\n            {\'apiVersion\':\'v1\',\'kind\':\'DeleteOptions\',\'preconditions\':{\'uid\':policy[\'metadata\'][\'uid\']}})\n        assert code in (200,202),(code,obj)\n        restored=service(s,target)\n        s.wait(lambda:dns_udp(s,client,restored) and dns_tcp(s,client,restored,dns[\'spec\'][\'clusterIP\']) and fetch(s,client,forbidden),10,\'actual DNS and HTTP recovery after removing only own policy\')\n        print(\'PRIVATE_NETWORK_FEATURE_READY\',flush=True)\n\ndef localpath_probe():\n    with NodeSession() as s:\n        storage=s.get(\'/apis/storage.k8s.io/v1/storageclasses/local-path\')\n        assert storage[\'provisioner\']==\'rancher.io/local-path\'\n        nonce=token(\'native-io\')\n        p=s.pod({\'containers\':[container(s,script=\'printf %s \'+nonce+\' > /native/value; exec sleep 3600\',volumeMounts=[{\'name\':\'disk\',\'mountPath\':\'/native\'}])],\n            \'volumes\':[{\'name\':\'disk\',\'ephemeral\':{\'volumeClaimTemplate\':{\'spec\':{\'accessModes\':[\'ReadWriteOnce\'],\'storageClassName\':\'local-path\',\'resources\':{\'requests\':{\'storage\':\'8Mi\'}}}}}}]})\n        name=p[\'metadata\'][\'name\'];live=s.ready_pod(name,25)\n        claim=s.get(s.path(\'persistentvolumeclaims\',name+\'-disk\'))\n        assert claim[\'status\'][\'phase\']==\'Bound\' and any(o[\'uid\']==p[\'metadata\'][\'uid\'] for o in claim[\'metadata\'][\'ownerReferences\'])\n        code,out,err=execution(s,name,[\'cat\',\'/native/value\']);assert code==0 and out==nonce,(code,out,err)\n        print(\'PRIVATE_LOCALPATH_IO_FEATURE_READY\',flush=True)\n\nif __name__==\'__main__\':\n    mode=sys.argv[1]\n    if mode==\'network\':network_probe()\n    elif mode==\'localpath\':localpath_probe()\n    else:raise RuntimeError(\'Unsupported trusted native capability\')\n'


PRIVATE_NODE_PROBE = r'''
import base64,hashlib,json,os,pathlib,re,secrets,ssl,subprocess,tempfile,time,urllib.error,urllib.parse,urllib.request
assert os.name=='posix' and os.geteuid()!=0
explicit=os.environ.get('KUBECONFIG','')
assert explicit and os.pathsep not in explicit,'Explicit single-file private kubeconfig required'
original=pathlib.Path(explicit)
assert original.is_file(),'Private kubeconfig unavailable'
baseline=hashlib.sha256(original.read_bytes()).hexdigest()
image=os.environ.get('OPSF_NODE_IMAGE','')
assert image in ('busybox:1.36.1','busybox@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662'),'Reviewed cached BusyBox image required'
proc=subprocess.run(['kubectl','--kubeconfig',str(original),'config','view','--raw','--flatten','-o','json'],capture_output=True,text=True,timeout=5)
assert proc.returncode==0,'Cannot read explicit private kubeconfig'
cfg=json.loads(proc.stdout);context=cfg['current-context']
ctx=next(x['context'] for x in cfg['contexts'] if x['name']==context)
cluster=next(x['cluster'] for x in cfg['clusters'] if x['name']==ctx['cluster'])
user=next(x['user'] for x in cfg['users'] if x['name']==ctx['user'])
url=urllib.parse.urlsplit(cluster['server'])
assert url.scheme=='https' and url.hostname in ('127.0.0.1','localhost','::1') and not url.username and not url.password and not url.query and not url.fragment,'Only TLS loopback private cluster is supported'
assert not cluster.get('insecure-skip-tls-verify') and cluster.get('certificate-authority-data'),'TLS CA validation required'
assert 'exec' not in user and 'auth-provider' not in user,'External credential execution is not supported'
server=cluster['server'].rstrip('/')
ns='opsforge-node-preflight-'+secrets.token_hex(6);owned=None
with tempfile.TemporaryDirectory(prefix='opsforge-private-node-probe-') as directory:
    root=pathlib.Path(directory);root.chmod(0o700)
    config=root/'config.json';config.write_text(json.dumps(cfg));config.chmod(0o600)
    tls=ssl.create_default_context(cadata=base64.b64decode(cluster['certificate-authority-data']).decode())
    if 'client-certificate-data' in user and 'client-key-data' in user:
        cert=root/'client.crt';key=root/'client.key'
        cert.write_bytes(base64.b64decode(user['client-certificate-data']))
        key.write_bytes(base64.b64decode(user['client-key-data']));key.chmod(0o600)
        tls.load_cert_chain(str(cert),str(key))
    bearer=user.get('token')
    if 'tokenFile' in user:bearer=pathlib.Path(user['tokenFile']).read_text().strip()
    def api(method,path,value=None):
        headers={'Content-Type':'application/json'}
        if bearer:headers['Authorization']='Bearer '+bearer
        request=urllib.request.Request(server+path,data=None if value is None else json.dumps(value).encode(),headers=headers,method=method)
        try:
            with urllib.request.urlopen(request,context=tls,timeout=3) as response:return response.status,json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code,json.loads(error.read())
    def read(path):
        code,obj=api('GET',path);assert code==200,'Private API access unavailable'
        return obj
    def fixed(command):
        proc=subprocess.run(['kubectl','--kubeconfig',str(config),'--context',context,'-n',ns,'--request-timeout=3s']+command,capture_output=True,text=True,timeout=5)
        assert proc.returncode==0,'Native kubelet evidence unavailable'
        return proc.stdout
    try:
        version=read('/version')['gitVersion']
        assert re.fullmatch(r'v1\.34\.1(?:\+[A-Za-z0-9.-]+)?',version),'Reviewed API version unavailable'
        nodes=read('/api/v1/nodes')['items']
        ready=[n for n in nodes if n['metadata'].get('labels',{}).get('hw')=='compute' and any(c['type']=='Ready' and c['status']=='True' for c in n.get('status',{}).get('conditions',[]))]
        assert ready and all(re.fullmatch(r'v1\.34\.1(?:\+[A-Za-z0-9.-]+)?',n['status']['nodeInfo']['kubeletVersion']) for n in ready),'Reviewed Ready kubelet unavailable'
        code,obj=api('POST','/api/v1/namespaces',{'apiVersion':'v1','kind':'Namespace','metadata':{'name':ns,'labels':{'opsforge-owned':'node-feature-preflight'}}})
        assert code==201,'Cannot create isolated preflight namespace'
        owned=obj['metadata']['uid']
        end=time.monotonic()+5
        while api('GET','/api/v1/namespaces/'+ns+'/serviceaccounts/default')[0]!=200:
            assert time.monotonic()<end,'Private service-account controller unavailable'
            time.sleep(.1)
        nonce=secrets.token_hex(16);name='native-image-probe'
        pod={'apiVersion':'v1','kind':'Pod','metadata':{'name':name},'spec':{'automountServiceAccountToken':False,'terminationGracePeriodSeconds':0,'nodeSelector':{'hw':'compute'},
            'containers':[{'name':'main','image':image,'imagePullPolicy':'Never','command':['sh','-c','echo '+nonce+'; sleep 3600'],
                           'resources':{'requests':{'cpu':'5m','memory':'4Mi'},'limits':{'cpu':'50m','memory':'32Mi'}}}]}}
        code,obj=api('POST','/api/v1/namespaces/'+ns+'/pods',pod);assert code==201,'Cannot create actual probe Pod'
        pod_uid=obj['metadata']['uid'];end=time.monotonic()+20
        while True:
            live=read('/api/v1/namespaces/'+ns+'/pods/'+name)
            assert live['metadata']['uid']==pod_uid,'Probe Pod identity changed'
            if any(c['type']=='Ready' and c['status']=='True' for c in live.get('status',{}).get('conditions',[])):break
            assert time.monotonic()<end,'Cached native Pod did not become Ready'
            time.sleep(.25)
        assert live['spec']['nodeName'] in {n['metadata']['name'] for n in ready},'Probe used an unexpected node'
        states=live['status']['containerStatuses']
        assert states[0]['imageID'] in ('sha256:b116e155074440ffd9e449559433feb4cd2341eb3554b1da1c638c976e56451d','docker.io/library/busybox@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662'),'Cached BusyBox does not match reviewed exact config or official index digest'
        assert fixed(['logs',name,'-c','main']).strip()==nonce,'Real native log marker unavailable'
        assert hashlib.sha256(original.read_bytes()).hexdigest()==baseline,'Original kubeconfig changed'
        print('PRIVATE_NODE_FEATURE_READY:'+json.dumps({'server':version,'kubelet':ready[0]['status']['nodeInfo']['kubeletVersion'],'pod_uid':pod_uid,'image_id':states[0]['imageID']},sort_keys=True))
    finally:
        if owned:
            code,obj=api('DELETE','/api/v1/namespaces/'+ns,{'apiVersion':'v1','kind':'DeleteOptions','preconditions':{'uid':owned}})
            assert code in (200,202,404),'Cannot clean private preflight namespace'
'''


PYTHON_FEATURE_PROBES = {
    'linux:file_backed_faults': 'import pathlib,subprocess,tempfile\nwith tempfile.TemporaryDirectory(prefix=\'opsf-file-fault-preflight-\') as temp:\n    root=pathlib.Path(temp);source=root/\'probe.c\';binary=root/\'probe\'\n    source.write_text(\'#define _GNU_SOURCE\\n#include <sys/mman.h>\\n#include <sys/resource.h>\\n#include <unistd.h>\\n#include <fcntl.h>\\n#include <stdlib.h>\\n#include <stdio.h>\\n#include <string.h>\\n#include <errno.h>\\n\\nint main(void) {\\n    long page=sysconf(_SC_PAGESIZE);\\n    const size_t pages=4;\\n    int fd=-1, status=2;\\n    char name[]="/tmp/opsf-file-fault-XXXXXX";\\n    unsigned char *source=NULL,*mapping=MAP_FAILED, resident[4]={0};\\n    struct rusage before={0},read_done={0},write_done={0};\\n    if(page<=0 || page>65536) goto cleanup;\\n    size_t bytes=(size_t)page*pages;\\n    source=malloc(bytes);if(!source) goto cleanup;\\n    memset(source,0x31,bytes);\\n    fd=mkstemp(name);if(fd<0) goto cleanup;\\n    if(write(fd,source,bytes)!=(ssize_t)bytes || fsync(fd)) goto cleanup;\\n    int advised=posix_fadvise(fd,0,(off_t)bytes,POSIX_FADV_DONTNEED);\\n    if(advised){errno=advised;goto cleanup;}\\n    mapping=mmap(NULL,bytes,PROT_READ|PROT_WRITE,MAP_PRIVATE,fd,0);\\n    if(mapping==MAP_FAILED || madvise(mapping,bytes,MADV_NOHUGEPAGE)) goto cleanup;\\n    if(mincore(mapping,bytes,resident)) goto cleanup;\\n    for(size_t i=0;i<pages;i++) if(resident[i]&1){errno=EBUSY;goto cleanup;}\\n    /* Warm the counter structures; process-wide counts are not an exact per-page I/O trace. */\\n    getrusage(RUSAGE_SELF,&before);getrusage(RUSAGE_SELF,&read_done);getrusage(RUSAGE_SELF,&write_done);\\n    volatile unsigned char *view=mapping;\\n    volatile unsigned long sum=0;\\n    if(getrusage(RUSAGE_SELF,&before)) goto cleanup;\\n    for(size_t i=0;i<pages;i++) sum+=view[i*(size_t)page];\\n    if(getrusage(RUSAGE_SELF,&read_done)) goto cleanup;\\n    for(size_t i=0;i<pages;i++) view[i*(size_t)page]=0x52;\\n    if(getrusage(RUSAGE_SELF,&write_done)) goto cleanup;\\n    unsigned char check;\\n    for(size_t i=0;i<pages;i++) {\\n        if(pread(fd,&check,1,(off_t)(i*(size_t)page))!=1 || check!=0x31 || view[i*(size_t)page]!=0x52) goto cleanup;\\n    }\\n    printf("{\\\\"page_size\\\\":%ld,\\\\"pages\\\\":%zu,\\\\"cold_file_major\\\\":%ld,\\\\"cold_file_minor\\\\":%ld,\\\\"cow_minor\\\\":%ld,\\\\"cow_major\\\\":%ld,\\\\"sum\\\\":%lu,\\\\"uid\\\\":%lu}\\\\n",page,pages,read_done.ru_majflt-before.ru_majflt,read_done.ru_minflt-before.ru_minflt,write_done.ru_minflt-read_done.ru_minflt,write_done.ru_majflt-read_done.ru_majflt,sum,(unsigned long)getuid());\\n    status=(read_done.ru_majflt>before.ru_majflt && write_done.ru_minflt-read_done.ru_minflt>=(long)pages && write_done.ru_majflt==read_done.ru_majflt)?0:3;\\ncleanup:\\n    if(status==2) fprintf(stderr,"file-fault capability unavailable: errno=%d (%s)\\\\n",errno,strerror(errno));\\n    if(mapping!=MAP_FAILED) munmap(mapping,(size_t)page*pages);\\n    if(fd>=0){close(fd);unlink(name);}\\n    free(source);\\n    return status;\\n}\\n\',encoding=\'utf8\')\n    subprocess.run([\'gcc\',\'-O0\',str(source),\'-o\',str(binary)],check=True,capture_output=True,timeout=3)\n    subprocess.run([str(binary)],check=True,capture_output=True,timeout=1)\n',
    'linux:character_devices': "import fcntl,os,stat\nfds=[]\ntry:\n    for path,mode in [('/dev/null',os.O_RDWR),('/dev/zero',os.O_RDONLY),('/dev/random',os.O_RDONLY|os.O_NONBLOCK)]:\n        fd=os.open(path,mode|os.O_CLOEXEC);fds.append(fd)\n        assert stat.S_ISCHR(os.fstat(fd).st_mode)\n    assert os.read(fds[0],8)==b'' and os.write(fds[0],b'probe')==5\n    assert os.read(fds[1],16)==bytes(16)\n    try:\n        value=os.read(fds[2],8);assert 0<len(value)<=8\n    except BlockingIOError:pass\nfinally:\n    for fd in fds:os.close(fd)\n",
    'linux:posix_mqueue': "import ctypes,errno,json,os,secrets\nclass Attr(ctypes.Structure):\n    _fields_=[('flags',ctypes.c_long),('maxmsg',ctypes.c_long),('msgsize',ctypes.c_long),('curmsgs',ctypes.c_long),('pad',ctypes.c_long*4)]\nlib=ctypes.CDLL(None,use_errno=True)\nlib.mq_open.restype=ctypes.c_int\nlib.mq_open.argtypes=[ctypes.c_char_p,ctypes.c_int,ctypes.c_uint,ctypes.POINTER(Attr)]\nlib.mq_close.argtypes=[ctypes.c_int];lib.mq_unlink.argtypes=[ctypes.c_char_p]\nlib.mq_send.argtypes=[ctypes.c_int,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint]\nlib.mq_receive.argtypes=[ctypes.c_int,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_uint)];lib.mq_receive.restype=ctypes.c_ssize_t\nname=b'/opsf-probe-'+secrets.token_hex(12).encode();fd=-1;owned=False\ntry:\n    fd=lib.mq_open(name,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NONBLOCK|os.O_CLOEXEC,0o600,ctypes.byref(Attr(0,2,128,0)))\n    if fd<0:raise OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()))\n    owned=True\n    assert lib.mq_send(fd,b'low',3,1)==0 and lib.mq_send(fd,b'high',4,2)==0\n    assert lib.mq_send(fd,b'full',4,0)==-1 and ctypes.get_errno()==errno.EAGAIN\n    assert lib.mq_unlink(name)==0;owned=False\n    assert lib.mq_open(name,os.O_RDWR|os.O_NONBLOCK,0,None)==-1 and ctypes.get_errno()==errno.ENOENT\n    buf=ctypes.create_string_buffer(128);priority=ctypes.c_uint()\n    n=lib.mq_receive(fd,buf,128,ctypes.byref(priority));assert n==4 and buf.raw[:n]==b'high' and priority.value==2\n    n=lib.mq_receive(fd,buf,128,ctypes.byref(priority));assert n==3 and buf.raw[:n]==b'low' and priority.value==1\n    assert lib.mq_receive(fd,buf,128,ctypes.byref(priority))==-1 and ctypes.get_errno()==errno.EAGAIN\n    print(json.dumps({'mq_available':True,'uid':os.getuid(),'capacity':2,'message_bytes':128,'priority_and_unlink_lifetime':True,'kernel':os.uname().release}))\nfinally:\n    if fd>=0:assert lib.mq_close(fd)==0\n    if owned:assert lib.mq_unlink(name)==0",
    'linux:nonblocking_pipe': '''import errno,fcntl,os,select,signal
assert signal.getsignal(signal.SIGPIPE)==signal.SIG_IGN
reader,writer=os.pipe2(os.O_NONBLOCK|os.O_CLOEXEC)
try:
    assert fcntl.fcntl(writer,fcntl.F_GETFL)&os.O_NONBLOCK
    assert fcntl.fcntl(writer,fcntl.F_GETFD)&fcntl.FD_CLOEXEC
    assert select.select([], [writer], [], 0)[1]==[writer]
    assert os.write(writer,b'probe')==5 and os.read(reader,5)==b'probe'
    os.close(reader);reader=None
    try:os.write(writer,b'x')
    except BrokenPipeError as exc:assert exc.errno==errno.EPIPE
    else:raise AssertionError('closed pipe did not report EPIPE')
finally:
    if reader is not None:os.close(reader)
    os.close(writer)
''',
    'linux:notify_socket': '''import os,pathlib,secrets,socket,struct,tempfile
with tempfile.TemporaryDirectory(prefix='opsf-notify-probe-') as tmp:
    for address in [os.fsencode(pathlib.Path(tmp)/'notify'),bytes([0])+b'opsf-notify-probe-'+secrets.token_hex(12).encode('ascii')]:
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as receiver, socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as sender:
            receiver.setsockopt(socket.SOL_SOCKET,socket.SO_PASSCRED,1)
            receiver.bind(address);receiver.settimeout(1)
            assert sender.sendto(b'opsf',address)==4
            data,control,flags,peer=receiver.recvmsg(16,socket.CMSG_SPACE(12))
            credentials=[struct.unpack('3i',value[:12]) for level,kind,value in control if level==socket.SOL_SOCKET and kind==socket.SCM_CREDENTIALS]
            assert data==b'opsf' and not flags and credentials==[(os.getpid(),os.getuid(),os.getgid())]
''',
    'linux:inotify_bounded_overflow': "import pathlib\nlimit=int(pathlib.Path('/proc/sys/fs/inotify/max_queued_events').read_text(encoding='ascii').strip())\nassert 1<=limit<=32768, 'inotify queue exceeds the bounded training workload; do not change host limits'\n",
    'linux:posix_shm': '''import ctypes, errno, fcntl, mmap, os, secrets
assert os.path.isdir('/proc/self/fd'), 'private process descriptor observation unavailable'
libc=ctypes.CDLL(None,use_errno=True)
libc.shm_open.argtypes=[ctypes.c_char_p,ctypes.c_int,ctypes.c_uint]
libc.shm_open.restype=ctypes.c_int
libc.shm_unlink.argtypes=[ctypes.c_char_p]
libc.shm_unlink.restype=ctypes.c_int
name=('/opsf-probe-'+secrets.token_hex(16)).encode('ascii')
first=second=-1;created=False
try:
    first=libc.shm_open(name,os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600)
    assert first>=0, 'private POSIX shared memory unavailable'
    created=True
    os.ftruncate(first,4096)
    with mmap.mmap(first,4096) as region:
        region[:4]=b'opsf';region.flush()
    second=libc.shm_open(name,os.O_RDWR,0)
    assert second>=0
    assert os.pread(second,4,0)==b'opsf'
    fcntl.flock(first,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:fcntl.flock(second,fcntl.LOCK_SH|fcntl.LOCK_NB)
    except BlockingIOError:pass
    else:raise RuntimeError('shared-memory holder locking unavailable')
    fcntl.flock(first,fcntl.LOCK_UN)
    fcntl.flock(second,fcntl.LOCK_SH|fcntl.LOCK_NB)
    assert libc.shm_unlink(name)==0
    created=False
    missing=libc.shm_open(name,os.O_RDWR,0)
    if missing>=0:
        os.close(missing)
        raise RuntimeError('private object name remained after unlink')
    assert ctypes.get_errno()==errno.ENOENT
finally:
    try:
        if created:libc.shm_unlink(name)
    finally:
        try:
            if second>=0:os.close(second)
        finally:
            if first>=0:os.close(first)
''',
    'linux:controlling_pty': '''import ctypes, fcntl, os, signal, termios
# execute() starts this fixed probe in its own session. No inherited terminal
# is used or modified; only the newly allocated private PTY is attached.
assert os.getsid(0)==os.getpid()
libc=ctypes.CDLL(None,use_errno=True)
subreaper=ctypes.c_int()
assert libc.prctl(37,ctypes.byref(subreaper),0,0,0)==0
try:
    assert libc.prctl(36,1,0,0,0)==0
finally:
    assert libc.prctl(36,subreaper.value,0,0,0)==0
master,slave=os.openpty()
previous=signal.signal(signal.SIGHUP,signal.SIG_IGN)
try:
    fcntl.ioctl(slave,termios.TIOCSCTTY,0)
    os.tcsetpgrp(slave,os.getpgrp())
    assert os.tcgetpgrp(slave)==os.getpgrp()
    os.write(master,b'x\\n')
    assert os.read(slave,2)==b'x\\n'
finally:
    os.close(slave)
    os.close(master)
    signal.signal(signal.SIGHUP,previous)
''',
    'gcc:static-libc': '''import os, pathlib, shutil, subprocess, tempfile
compiler=shutil.which('gcc',path=os.defpath)
assert compiler, 'trusted system gcc unavailable'
with tempfile.TemporaryDirectory(prefix='opsf-static-libc-probe-') as temp:
    root=pathlib.Path(temp);source=root/'probe.c';program=root/'probe'
    source.write_text('#include <stdio.h>\\nint main(void){return puts("opsforge-static")<0;}\\n',encoding='ascii')
    env={'PATH':os.defpath,'LC_ALL':'C','HOME':temp,'TMPDIR':temp}
    subprocess.run([compiler,'-static','-O0',str(source),'-o',str(program)],cwd=root,env=env,
                   stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                   timeout=2,check=True)
    result=subprocess.run([str(program)],cwd=root,env=env,stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=1,check=True)
    assert result.stdout==b'opsforge-static\\n', 'static libc executable failed its controlled probe'
''',
    'linux:ctime_ns': "import os,pathlib,tempfile,time\nwith tempfile.TemporaryDirectory(prefix='opsforge-ctime-probe-') as tmp:\n    path=pathlib.Path(tmp)/'file';path.write_bytes(b'old')\n    target=946684800000000123\n    os.utime(path,ns=(target,target));old=path.stat()\n    assert old.st_mtime_ns==target\n    time.sleep(0.02)\n    path.write_bytes(b'new');os.utime(path,ns=(target,target));new=path.stat()\n    assert new.st_ino==old.st_ino and new.st_mtime_ns==target and new.st_ctime_ns>old.st_ctime_ns\n",
    'linux:smaps': "import mmap, pathlib, tempfile\nwith tempfile.TemporaryDirectory(prefix='opsforge-smaps-probe-') as tmp:\n    path=pathlib.Path(tmp)/'page'\n    path.write_bytes(b'x'*mmap.PAGESIZE)\n    with path.open('r+b') as f, mmap.mmap(f.fileno(),0,access=mmap.ACCESS_WRITE) as region:\n        region[0]=region[0]\n        active=False;fields={}\n        for line in pathlib.Path('/proc/self/smaps').read_text().splitlines():\n            if '-' in line.split(' ',1)[0]:\n                active=line.endswith(str(path))\n            elif active and ':' in line:\n                key,value=line.split(':',1);fields[key]=value.strip()\n        assert int(fields['Rss'].split()[0])>=mmap.PAGESIZE//1024\n        assert int(fields['Pss'].split()[0])>=mmap.PAGESIZE//1024\n",
    'linux:abstract_unix_lock': '''import ctypes, errno, secrets, socket
libc=ctypes.CDLL(None,use_errno=True)
previous=ctypes.c_int()
assert libc.prctl(37,ctypes.byref(previous),0,0,0)==0, 'subreaper status unavailable'
try:
    assert libc.prctl(36,1,0,0,0)==0, 'subreaper unavailable'
    current=ctypes.c_int()
    assert libc.prctl(37,ctypes.byref(current),0,0,0)==0 and current.value==1
    address=bytes([0])+b'opsf-probe-'+secrets.token_hex(12).encode('ascii')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as owner:
        owner.bind(address)
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as contender:
            try:contender.bind(address)
            except OSError as exc:assert exc.errno==errno.EADDRINUSE
            else:raise RuntimeError('abstract socket is not exclusive')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as released:
        released.bind(address)
finally:
    assert libc.prctl(36,previous.value,0,0,0)==0, 'restore subreaper status failed'
''',
    'linux:inotify': '''import ctypes, os, pathlib, struct, tempfile
libc=ctypes.CDLL(None,use_errno=True)
libc.inotify_init1.argtypes=[ctypes.c_int];libc.inotify_init1.restype=ctypes.c_int
libc.inotify_add_watch.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_uint32]
libc.inotify_add_watch.restype=ctypes.c_int
fd=libc.inotify_init1(os.O_NONBLOCK|os.O_CLOEXEC)
assert fd>=0, 'inotify instance unavailable'
try:
    with tempfile.TemporaryDirectory(prefix='opsf-inotify-probe-') as temp:
        wd=libc.inotify_add_watch(fd,os.fsencode(temp),0x100)
        assert wd>=0, 'inotify watch unavailable'
        (pathlib.Path(temp)/'probe').write_bytes(b'')
        data=os.read(fd,4096)
        observed,mask,cookie,length=struct.unpack_from('iIII',data)
        assert observed==wd and mask&0x100 and data[16:16+length].split(bytes([0]),1)[0]==b'probe'
finally:
    os.close(fd)
''',
    'linux:affinity': "import os\noriginal=os.sched_getaffinity(0)\nassert len(original)>=2, 'needs at least two currently permitted CPUs'\ntry:\n    os.sched_setaffinity(0,{min(original)})\n    assert os.sched_getaffinity(0)=={min(original)}\nfinally:\n    os.sched_setaffinity(0,original)\nassert os.sched_getaffinity(0)==original\n",
    'linux:nonroot_dac': "import errno, os, pathlib, tempfile\nassert os.geteuid() != 0, 'requires ordinary nonroot DAC enforcement'\nwith tempfile.TemporaryDirectory(prefix='opsf-dac-probe-') as temp:\n    path=pathlib.Path(temp)/'owned';path.write_bytes(b'x')\n    fd=os.open(path,os.O_RDONLY)\n    try:\n        os.fchmod(fd,0)\n        try:\n            other=os.open(path,os.O_RDONLY)\n        except OSError as exc:\n            assert exc.errno == errno.EACCES\n        else:\n            os.close(other)\n            raise RuntimeError('DAC bypassed by environment')\n        assert os.read(fd,1)==b'x'\n    finally:\n        os.fchmod(fd,0o600)\n        os.close(fd)\n",
    'linux:openat2': 'import os, pathlib, shutil, subprocess, tempfile\ncompiler=shutil.which(\'gcc\',path=os.defpath)\nassert compiler, \'trusted system gcc unavailable\'\nwith tempfile.TemporaryDirectory(prefix=\'opsf-openat2-probe-\') as temp:\n    root=pathlib.Path(temp);source=root/\'probe.c\';program=root/\'probe\'\n    source.write_text(\'#define _GNU_SOURCE\\n#include <fcntl.h>\\n#include <unistd.h>\\n#include <sys/syscall.h>\\n#include <linux/openat2.h>\\nint main(void) {\\n    int root=open(".",O_PATH|O_DIRECTORY|O_CLOEXEC);\\n    if(root<0)return 2;\\n    struct open_how how={.flags=O_PATH|O_DIRECTORY|O_CLOEXEC,\\n        .resolve=RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS};\\n    int fd=syscall(__NR_openat2,root,".",&how,sizeof(how));\\n    close(root);\\n    if(fd<0)return 3;\\n    close(fd);return 0;\\n}\\n\',encoding=\'ascii\')\n    env={\'PATH\':os.defpath,\'LC_ALL\':\'C\',\'HOME\':temp,\'TMPDIR\':temp}\n    subprocess.run([compiler,\'-O0\',str(source),\'-o\',str(program)],cwd=root,env=env,\n                   stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,\n                   timeout=2,check=True)\n    subprocess.run([str(program)],cwd=root,env=env,stdin=subprocess.DEVNULL,\n                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=1,check=True)\n',
    'locale:c_utf8': '''import locale
locale.setlocale(locale.LC_CTYPE, 'C.UTF-8')
assert locale.nl_langinfo(locale.CODESET).replace('-', '').lower() == 'utf8'
''',
    'linux:mincore': '''import ctypes, mmap
page = mmap.PAGESIZE
region = mmap.mmap(-1, page, flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS,
                   prot=mmap.PROT_READ | mmap.PROT_WRITE)
try:
    region.madvise(mmap.MADV_NOHUGEPAGE)
    address = ctypes.addressof(ctypes.c_char.from_buffer(region))
    vector = (ctypes.c_ubyte * 1)()
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mincore.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_ubyte)]
    libc.mincore.restype = ctypes.c_int
    if libc.mincore(address, page, vector) != 0:
        raise OSError(ctypes.get_errno(), 'mincore unavailable')
    region[0] = 1
    if libc.mincore(address, page, vector) != 0:
        raise OSError(ctypes.get_errno(), 'mincore unavailable')
    assert vector[0] & 1
finally:
    region.close()
''',
}


def terminate(process):
    try:
        if os.name == 'posix':
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass


def execute(command, timeout):
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=os.name == 'posix')
    chunks, size, overflow = [], 0, False

    def read():
        nonlocal size, overflow
        while True:
            chunk = process.stdout.read(4096)
            if not chunk:
                return
            size += len(chunk)
            if size > 200000:
                overflow = True
                terminate(process)
                return
            chunks.append(chunk)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    expired = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        expired = True
        terminate(process)
        process.wait(timeout=5)
    finally:
        # The checker can exit while learner-created descendants still run or
        # retain its stdout pipe. Its process group belongs only to this check.
        if os.name == 'posix':
            terminate(process)
    reader.join(timeout=5)
    output = b''.join(chunks).decode('utf-8', errors='replace')
    if not reader.is_alive():
        process.stdout.close()
    return process.returncode, output, expired or overflow or reader.is_alive()


def require_nginx_stream(output, executable, ssl_preread=False):
    flags = output.split()
    load = ''
    if '--with-stream' not in flags:
        if '--with-stream=dynamic' not in flags:
            raise FileNotFoundError('required tool feature unavailable: nginx:stream')
        directory = next((flag.split('=', 1)[1] for flag in flags if flag.startswith('--modules-path=')), '')
        module = Path(directory) / 'ngx_stream_module.so'
        if not module.is_absolute() or not module.is_file():
            raise FileNotFoundError('required Nginx stream module unavailable')
        load = 'load_module ' + json.dumps(str(module)) + ';\n'
    # Parse a no-listener configuration: existence of a .so does not prove it
    # can be loaded by this Nginx binary and its dependency versions.
    with tempfile.TemporaryDirectory(prefix='opsforge-stream-preflight-') as directory:
        root = Path(directory)
        config = root / 'nginx.conf'
        stream = 'stream { ssl_preread on; }' if ssl_preread else 'stream {}'
        config.write_text(load + 'pid ' + json.dumps(str(root/'nginx.pid'))
                          + ';\nerror_log stderr;\nevents {}\n' + stream + '\n', encoding='utf-8')
        code, _, interrupted = execute([executable, '-t', '-p', str(root), '-c', str(config)], 5)
        if code != 0 or interrupted:
            raise FileNotFoundError('required Nginx stream module failed to load')


def require_features(features):
    probes = {}
    flags = {'nginx:http_v2': '--with-http_v2_module',
             'nginx:secure_link': '--with-http_secure_link_module',
             'nginx:slice': '--with-http_slice_module',
             'nginx:auth_request': '--with-http_auth_request_module',
             'nginx:realip': '--with-http_realip_module'}
    versions = {'prometheus:v3.5': '3.5', 'promtool:v3.5': '3.5',
                'alertmanager:v0.28': '0.28', 'amtool:v0.28': '0.28', 'node_exporter:v1.9': '1.9'}
    for feature in features:
        if feature == 'tiflash:replica-v8.5.4':
            binaries={
                '/opt/tiflash/tiflash':'76e170fd01597f26ec229f68b9f10714b7f46f7473a0780e5810f70249b0b75a',
                '/opt/tiflash/libtiflash_proxy.so':'66c8468318935f36ec60b50c55ba20fc3073e831b7d1b0d86a1c936239fce579',
            }
            if sys.platform!='linux' or not hasattr(os,'geteuid') or os.geteuid()==0:
                raise FileNotFoundError('Reviewed non-root TiFlash environment unavailable')
            for filename,expected in binaries.items():
                binary=Path(filename)
                if not binary.is_file():
                    raise FileNotFoundError('Reviewed TiFlash binary or proxy unavailable')
                with binary.open('rb') as stream:
                    digest=hashlib.file_digest(stream,'sha256').hexdigest()
                if digest!=expected:
                    raise FileNotFoundError('Reviewed TiFlash binary or proxy digest unavailable')
            code,version,interrupted=execute(['/opt/tiflash/tiflash','--version'],5)
            if code or interrupted or not re.search(r'^Release Version: v8\.5\.4$',version,re.MULTILINE):
                raise FileNotFoundError('Reviewed TiFlash v8.5.4 executable unavailable')
            continue
        if feature == 'br:snapshot-v8.5.4':
            binary=Path('/usr/local/bin/br')
            if sys.platform!='linux' or os.geteuid()==0 or not binary.is_file():
                raise FileNotFoundError('Reviewed non-root native BR environment unavailable')
            with binary.open('rb') as stream:
                digest=hashlib.file_digest(stream,'sha256').hexdigest()
            if digest!='c3e49016423207e9ad07af315484399f431cda96c6ee6b05e14c7e1d3d3dcc46':
                raise FileNotFoundError('Reviewed BR binary digest unavailable')
            code,version,interrupted=execute([str(binary),'--version'],5)
            if code or interrupted or not re.search(r'^Release Version: v8\.5\.4$',version,re.MULTILINE):
                raise FileNotFoundError('Reviewed BR v8.5.4 executable unavailable')
            continue
        if feature == 'java:jdk-v17':
            for tool,pattern in [('java',r'version "17\.'),('javac',r'^javac 17\.')]:
                executable=shutil.which(tool)
                if not executable:
                    raise FileNotFoundError('Reviewed Java 17 JDK is unavailable')
                code,version,interrupted=execute([executable,'-version'],5)
                if code or interrupted or not re.search(pattern,version,re.MULTILINE):
                    raise FileNotFoundError('Reviewed Java 17 JDK is unavailable')
            continue
        if feature in ('kubernetes:private-network-v1.34.1', 'kubernetes:private-localpath-v1.34.1'):
            if sys.platform!='linux' or not hasattr(os,'geteuid') or os.geteuid()==0 or not shutil.which('kubectl'):
                raise FileNotFoundError('Private Kubernetes native capabilities require non-root Linux and kubectl')
            mode='network' if feature=='kubernetes:private-network-v1.34.1' else 'localpath'
            marker='PRIVATE_NETWORK_FEATURE_READY' if mode=='network' else 'PRIVATE_LOCALPATH_IO_FEATURE_READY'
            code,output,interrupted=execute([sys.executable,'-I','-B','-c',PRIVATE_NODE_CAPABILITIES_PROBE,mode],80)
            if code or interrupted or marker not in output:
                raise FileNotFoundError('Private Kubernetes native '+mode+' capability unavailable')
            continue
        if feature == 'kubernetes:private-node-v1.34.1':
            if sys.platform!='linux' or not hasattr(os,'geteuid') or os.geteuid()==0 or not shutil.which('kubectl'):
                raise FileNotFoundError('Private Kubernetes node workspaces require non-root Linux and kubectl')
            code,output,interrupted=execute([sys.executable,'-I','-B','-c',PRIVATE_NODE_PROBE],40)
            if code or interrupted or 'PRIVATE_NODE_FEATURE_READY:' not in output:
                raise FileNotFoundError('Private Kubernetes v1.34.1 node or reviewed cached image unavailable')
            continue
        if feature in ('kafka:kraft-v4.0.0', 'tidb:cluster-v8.5.4'):
            if sys.platform != 'linux' or os.geteuid() == 0:
                raise FileNotFoundError('native distributed services require non-root Linux')
            if feature == 'kafka:kraft-v4.0.0':
                java = shutil.which('java')
                home = Path('/opt/kafka')
                if not java or not all((home/'bin'/name).is_file() for name in
                                       ('kafka-server-start.sh', 'kafka-storage.sh', 'kafka-run-class.sh')):
                    raise FileNotFoundError('native Kafka distribution unavailable')
                code, version, interrupted = execute([java, '-version'], 5)
                if code or interrupted or not re.search(r'version "(?:17|21)\.', version):
                    raise FileNotFoundError('Kafka requires the reviewed Java 17/21 runtime')
                if not (home/'libs/kafka_2.13-4.0.0.jar').is_file():
                    raise FileNotFoundError('native Kafka 4.0.0 jars unavailable')
            else:
                # Kubernetes has no per-Pod pid-limit field. Dedicated nodes must
                # provide sufficient kubelet podPidsLimit; do not silently score
                # process exhaustion as an incorrect learner solution.
                limit_path = Path('/sys/fs/cgroup/pids.max')
                if not limit_path.is_file():
                    raise FileNotFoundError('TiDB requires readable cgroup PID limits')
                limit = limit_path.read_text(encoding='ascii').strip()
                if limit != 'max' and (not limit.isdecimal() or int(limit) < 768):
                    raise FileNotFoundError('TiDB multi-store exercises require a PID budget of at least 768')
                for tool in ('tidb-server', 'pd-server', 'tikv-server'):
                    binary = shutil.which(tool)
                    if not binary:
                        raise FileNotFoundError('required native binary unavailable: '+tool)
                    code, version, interrupted = execute([binary, '-V'], 5)
                    if code or interrupted or not re.search(r'(?<![\d.])v?8\.5\.4(?![\d.])', version):
                        raise FileNotFoundError('required native version unavailable: '+tool)
            continue
        if feature == 'docker:daemon':
            # Only the dedicated DinD sidecar uses this explicit loopback
            # endpoint. Never fall back to a host socket or saved context.
            endpoint = 'tcp://127.0.0.1:2375'
            if sys.platform != 'linux' or os.geteuid() == 0 or os.getenv('DOCKER_HOST') != endpoint:
                raise FileNotFoundError('Docker exercises require the dedicated non-root Docker workspace')
            executable = shutil.which('docker')
            if not executable:
                raise FileNotFoundError('required tool unavailable: docker')
            code, output, interrupted = execute([executable, '--host', endpoint, 'info', '--format', '{{json .}}'], 5)
            try:
                info = json.loads(output)
                valid = info.get('OSType') == 'linux' and bool(info.get('ServerVersion'))
            except (ValueError, TypeError, AttributeError):
                valid = False
            if code != 0 or interrupted or not valid:
                raise FileNotFoundError('dedicated Docker daemon unavailable; check the DinD workspace')
            continue
        if feature in PYTHON_FEATURE_PROBES:
            if sys.platform != 'linux':
                raise FileNotFoundError('required Linux capability unavailable: ' + feature)
            if feature not in probes:
                # Fixed platform code, never question-provided code. Isolated
                # Python excludes learner files/PYTHONPATH from import lookup.
                code, _, interrupted = execute(
                    [sys.executable, '-I', '-B', '-c', PYTHON_FEATURE_PROBES[feature]], 5)
                if code != 0 or interrupted:
                    raise FileNotFoundError('required Linux capability unavailable: ' + feature)
                probes[feature] = True
            continue
        if feature == 'envtest:kubernetes-v1.34.1':
            # Missing resource accounting is an environment failure, not a
            # failed learner assertion inside the disposable control plane.
            if sys.platform != 'linux' or not hasattr(os, 'geteuid') or os.geteuid() == 0:
                raise FileNotFoundError('envtest requires an isolated non-root Linux workspace')
            try:
                candidates = (Path('/sys/fs/cgroup/opsforge-validation/memory.current'),
                              Path('/sys/fs/cgroup/memory.current'))
                memory_path = next((path for path in candidates if path.is_file()), None)
                if memory_path is None:
                    raise FileNotFoundError('memory controller is not mounted')
                memory = memory_path.read_text(encoding='ascii').strip()
                if not memory or not memory.isascii() or not memory.isdecimal():
                    raise ValueError('invalid memory accounting')
            except (OSError, UnicodeError, ValueError) as exc:
                raise FileNotFoundError('envtest requires readable cgroup v2 memory accounting') from exc
            # Version probes never create a listener or connect to a cluster.
            # The reviewed checker owns the isolated, temporary control plane.
            for binary, pattern in [('kube-apiserver', r'^Kubernetes v1\.34\.1\s*$'),
                                    ('etcd', r'^etcd Version: 3\.6\.4\r?$')]:
                if binary not in probes:
                    executable = shutil.which(binary)
                    if not executable:
                        raise FileNotFoundError('required tool unavailable: ' + binary)
                    code, output, interrupted = execute([executable, '--version'], 5)
                    if code != 0 or interrupted:
                        raise FileNotFoundError('required tool capabilities unavailable: ' + binary)
                    probes[binary] = (output, executable)
                if not re.search(pattern, probes[binary][0], re.MULTILINE):
                    raise FileNotFoundError('required reviewed tool version unavailable: ' + feature)
            continue
        if feature not in {*flags, *versions, 'bird:v2', 'kubectl:v1.34-kustomize5.7', 'traefik:v3.5', 'keepalived:v2.2', 'mysqld:v8.4', 'docker-compose:v5.1', 'curl:http2', 'nginx:stream', 'nginx:stream_ssl_preread', 'nginx:mirror'}:
            raise ValueError('unsupported reviewed tool feature')
        tool = feature.split(':', 1)[0]
        if tool not in probes:
            executable = shutil.which(tool)
            if not executable:
                raise FileNotFoundError('required tool unavailable: ' + tool)
            arguments = (['version', '--client=true', '--output=json'] if tool == 'kubectl'
                         else ['version', '--short'] if tool == 'docker-compose'
                         else ['version'] if tool == 'traefik'
                         else ['--no-defaults', '--version'] if tool == 'mysqld'
                         else ['--version' if feature in versions or feature in {'bird:v2','keepalived:v2.2','mysqld:v8.4'} else '-V'])
            code, output, interrupted = execute([executable, *arguments], 5)
            if code != 0 or interrupted:
                raise FileNotFoundError('required tool capabilities unavailable: ' + tool)
            probes[tool] = (output, executable)
        output, executable = probes[tool]
        if feature == 'docker-compose:v5.1':
            if not re.fullmatch(r'v?5\.1\.\d+\s*', output):
                raise FileNotFoundError('required reviewed tool version unavailable: ' + feature)
            continue
        if feature == 'mysqld:v8.4':
            if not re.search(r'\bmysqld(?:\.(?i:exe))?\s+Ver 8\.4\.\d+\s+[^\r\n]*\(MySQL Community Server - GPL\)', output):
                raise FileNotFoundError('required reviewed tool version unavailable: ' + feature)
            if os.name == 'posix':
                if not sys.platform.startswith('linux') or os.geteuid() == 0:
                    raise FileNotFoundError('MySQL exercises require an isolated non-root Linux workspace')
                try:
                    getattr(ctypes.CDLL(None), 'prctl')
                except (OSError, AttributeError) as exc:
                    raise FileNotFoundError('MySQL parent-death guard unavailable') from exc
            elif os.name == 'nt':
                for function in ('CreateJobObjectW', 'SetInformationJobObject', 'AssignProcessToJobObject'):
                    if not hasattr(ctypes.windll.kernel32, function):
                        raise FileNotFoundError('MySQL process Job guard unavailable')
            else:
                raise FileNotFoundError('MySQL isolated execution platform unavailable')
            continue
        if feature == 'keepalived:v2.2':
            if not re.search(r'^Keepalived v2\.2\.\d+(?:\s|$)', output, re.MULTILINE):
                raise FileNotFoundError('required reviewed tool version unavailable: ' + feature)
            continue
        if feature == 'traefik:v3.5':
            if not re.search(r'^Version:[ \t]+3\.5\.\d+(?:\r?$)', output, re.MULTILINE):
                raise FileNotFoundError('required reviewed tool version unavailable: ' + feature)
            continue
        if feature == 'kubectl:v1.34-kustomize5.7':
            try:
                info = json.loads(output)
                valid = (re.fullmatch(r'v1\.34\.\d+', info['clientVersion']['gitVersion'])
                         and re.fullmatch(r'v5\.7\.\d+', info['kustomizeVersion']))
            except (ValueError, KeyError, TypeError):
                valid = False
            if not valid:
                raise FileNotFoundError('required reviewed tool version unavailable: ' + feature)
            continue
        if feature == 'bird:v2':
            if not re.search(r'^BIRD version 2\.\d+(?:\.\d+)?(?:\s|$)', output, re.MULTILINE):
                raise FileNotFoundError('required reviewed tool version unavailable: bird:v2')
            continue
        if feature in versions:
            pattern = r'^' + re.escape(tool) + r', version ' + re.escape(versions[feature]) + r'\.\d+(?:\s|$)'
            if not re.search(pattern, output, re.MULTILINE):
                raise FileNotFoundError('required reviewed tool version unavailable: ' + feature)
            continue
        if feature == 'nginx:mirror':
            # The mirror module is normally built by default. Parse an actual
            # directive instead of assuming absence of a --without flag means
            # it works. No server/listen or learner files are involved.
            with tempfile.TemporaryDirectory(prefix='opsforge-mirror-preflight-') as directory:
                root = Path(directory)
                config = root / 'nginx.conf'
                config.write_text('pid ' + json.dumps(str(root/'nginx.pid'))
                                  + ';\nerror_log stderr;\nevents {}\nhttp { access_log off; mirror /probe; }\n', encoding='utf-8')
                code, _, interrupted = execute([executable, '-t', '-p', str(root), '-c', str(config)], 5)
                if code != 0 or interrupted:
                    raise FileNotFoundError('required Nginx mirror module unavailable')
            continue
        if feature in {'nginx:stream', 'nginx:stream_ssl_preread'}:
            require_nginx_stream(output, executable, ssl_preread=feature.endswith('_ssl_preread'))
            continue
        if feature in flags:
            available = flags[feature] in output.split()
        else:
            available = any(line.startswith('Features:') and 'HTTP2' in line.split()[1:]
                            for line in output.splitlines())
        if not available:
            raise FileNotFoundError('required tool feature unavailable: ' + feature)


def evaluate(spec):
    for name in spec.get('requires', {}).get('commands', []):
        override = {'helm': 'OPSF_HELM_BIN', 'bash': 'OPSFORGE_BASH', 'terraform': 'OPSFORGE_TERRAFORM'}.get(name)
        executable = os.environ.get(override, name) if override else name
        if not shutil.which(executable):
            raise FileNotFoundError('required tool unavailable: ' + name)
    for name in spec.get('requires', {}).get('python_modules', []):
        if importlib.util.find_spec(name) is None:
            raise ModuleNotFoundError('required module unavailable: ' + name)
    require_features(spec.get('requires', {}).get('features', []))
    for provider in spec.get('requires', {}).get('terraform_providers', []):
        if provider != 'hashicorp/local@2.5.3':
            raise ValueError('unsupported reviewed Terraform provider')
        machine = platform.machine().lower()
        arch = {'amd64':'amd64','x86_64':'amd64','arm64':'arm64','aarch64':'arm64'}.get(machine)
        system = platform.system().lower()
        root = Path(os.environ.get('OPSFORGE_TF_PROVIDER_MIRROR', '/opt/terraform-providers'))
        if not root.is_absolute() or not arch or system not in ('windows','linux'):
            raise FileNotFoundError('required provider platform unavailable: ' + provider)
        directory = root / 'registry.terraform.io/hashicorp/local/2.5.3' / (system + '_' + arch)
        binaries = list(directory.glob('terraform-provider-local_v2.5.3*'))
        if not any(p.is_file() and p.stat().st_size > 0 and os.access(p, os.X_OK) for p in binaries):
            raise FileNotFoundError('required offline provider unavailable: ' + provider)
    command = spec['command']
    marker = '__OPSF_CHECKS_COMPLETE_' + secrets.token_hex(24) + '__'
    if command == 'python3 checks/check.py':
        wrapper = 'import runpy;runpy.run_path("checks/check.py",run_name="__main__");print(' + repr(marker) + ')'
        args = [sys.executable, '-B', '-c', wrapper]
    elif command == 'go test -count=1 -timeout=20s ./...':
        args = ['go', 'test', '-json', '-count=1', '-timeout=20s', './...']
    else:
        raise ValueError('unsupported reviewed check command')
    code, output, interrupted = execute(args, spec['timeout'])
    complete = False
    if command.startswith('python3'):
        complete = marker in output.splitlines()
        output = output.replace(marker, '')
    else:
        expected = {tuple(item) for item in spec['go_tests']}
        passed = set()
        for line in output.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('Action') == 'pass' and event.get('Test'):
                passed.add((event.get('Package'), event['Test']))
        complete = bool(expected) and expected <= passed
    return {'passed': code == 0 and complete and not interrupted,
            'completed': complete, 'exit_code': code, 'interrupted': interrupted,
            'output': output[-6000:]}


if __name__ == '__main__':
    token = sys.argv[1]
    if not re.fullmatch('[a-f0-9]{48}', token):
        raise SystemExit(2)
    try:
        result = evaluate(json.loads(Path('checks/_opsforge_spec.json').read_text(encoding='utf-8')))
    except Exception as error:
        result = {'passed': False, 'completed': False, 'error': type(error).__name__}
    print('__OPSF_VERDICT_' + token + '__' + json.dumps(result, ensure_ascii=True))
    raise SystemExit(0 if result['passed'] else 1)
