"""Starter-pack anonymous manifest check, blob checks, then logged-out Docker pull."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.request
from datetime import datetime, timezone


def verify(image, output):
    if not image.startswith('ghcr.io/') or '@sha256:' not in image:
        raise ValueError('Use an immutable ghcr.io/owner/image@sha256:digest reference')
    repository,digest=image.removeprefix('ghcr.io/').split('@',1)
    # Deliberately no GitHub token, Docker credentials, or Authorization header.
    url=f'https://ghcr.io/token?scope=repository:{repository}:pull&service=ghcr.io'
    with urllib.request.urlopen(url,timeout=30) as response:
        token=json.load(response)['token']
    headers={'Authorization':f'Bearer {token}',
             'Accept':'application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json'}
    manifests=[]
    def manifest(ref):
        request=urllib.request.Request(f'https://ghcr.io/v2/{repository}/manifests/{ref}',headers=headers)
        with urllib.request.urlopen(request,timeout=30) as response:
            body=response.read();status=response.status
        actual='sha256:'+hashlib.sha256(body).hexdigest()
        assert actual==ref,(actual,ref)
        manifests.append({'digest':ref,'http_status':status})
        return json.loads(body)
    document=manifest(digest)
    if 'manifests' in document:
        descriptor=next(x for x in document['manifests'] if x.get('platform',{}).get('os')=='linux' and x.get('platform',{}).get('architecture')=='amd64')
        document=manifest(descriptor['digest'])
    blobs=[]
    for blob in [document['config'],*document['layers']]:
        request=urllib.request.Request(f'https://ghcr.io/v2/{repository}/blobs/{blob["digest"]}',headers=headers,method='HEAD')
        with urllib.request.urlopen(request,timeout=60) as response:
            assert response.status==200
            blobs.append({'digest':blob['digest'],'http_status':response.status,'bytes':blob['size']})
    env=os.environ.copy()
    if 'DOCKER_HOST' not in env:
        env['DOCKER_HOST']=subprocess.check_output(['docker','context','inspect','--format','{{.Endpoints.docker.Host}}'],text=True).strip()
    env.pop('DOCKER_CONTEXT',None)
    env.pop('DOCKER_AUTH_CONFIG',None)
    with tempfile.TemporaryDirectory(prefix='ghcr-anonymous-') as config:
        Path(config,'config.json').write_text('{"auths":{}}\n')
        env['DOCKER_CONFIG']=config
        subprocess.run(['docker','pull','--platform','linux/amd64',image],env=env,check=True)
        info=json.loads(subprocess.check_output(['docker','image','inspect',image],env=env,text=True))[0]
    assert info['Os']=='linux' and info['Architecture']=='amd64'
    assert info['Config']['User'] not in ('','0','root')
    assert not info['Config'].get('Volumes')
    result={'image':image,'checked_at':datetime.now(timezone.utc).isoformat(),
            'token_request':'anonymous; no credentials','manifests':manifests,'blobs':blobs,
            'docker_pull':'passed with fresh empty DOCKER_CONFIG',
            'architecture':'linux/amd64','user':info['Config']['User'],'volumes':None}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    parser.add_argument('--out',type=Path,default=Path('reports/phase2/anonymous-pull.json'))
    args=parser.parse_args()
    verify(args.image,args.out)
