"""Cold pull into a disposable Docker daemon; never prune the user's daemon."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import uuid


def main():
    p=argparse.ArgumentParser();p.add_argument('--image',required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if not a.image.startswith('ghcr.io/') or '@sha256:' not in a.image:
        raise ValueError('Immutable public GHCR image required')
    name='alignment-cold-'+uuid.uuid4().hex[:10]
    def run(*args):
        result=subprocess.run(['docker',*args],capture_output=True,text=True,timeout=600)
        if result.returncode:
            raise RuntimeError(f'Docker failed ({result.returncode}): {result.stderr[-2000:]}')
        return result
    try:
        run('run','--rm','-d','--privileged','--name',name,'--cpus=1','--memory=2g',
            '--tmpfs','/var/lib/docker:rw,size=4g','-e','DOCKER_TLS_CERTDIR=',
            'docker:27-dind','--host=unix:///var/run/docker.sock','--storage-driver=overlay2')
        for _ in range(60):
            try:
                run('exec',name,'docker','info');break
            except RuntimeError:
                time.sleep(.5)
        else:raise RuntimeError('Disposable daemon failed to start')
        assert not run('exec',name,'docker','image','ls','-q').stdout.strip()
        start=time.monotonic()
        result=run('exec',name,'docker','pull','--platform','linux/amd64',a.image)
        elapsed=time.monotonic()-start
        info=json.loads(run('exec',name,'docker','image','inspect',a.image).stdout)[0]
        assert info['Os']=='linux' and info['Architecture']=='amd64'
        a.out.parent.mkdir(parents=True,exist_ok=True)
        a.out.with_suffix('.log').write_text(result.stdout+result.stderr)
        a.out.write_text(json.dumps(dict(image=a.image,image_id=info['Id'],seconds=elapsed,
            daemon='disposable docker:27-dind, fresh tmpfs image store',initial_images=0,
            anonymous=True,platform='linux/amd64',no_existing_images_removed=True),indent=2)+'\n')
        print(a.out.read_text())
    finally:
        subprocess.run(['docker','rm','-f',name],capture_output=True)


if __name__=='__main__':main()
