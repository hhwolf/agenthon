"""Prepare/check release metadata. Does not publish, pack, or handle Team Keys."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from t2eval.final_release import make_descriptor, require

BUILD_INPUTS = {'Dockerfile', 'requirements-runtime.txt', '.dockerignore', 'LICENSE'}


def read(path):
    return json.loads(Path(path).read_text())


def release_preflight(root=Path('.')):
    release = read(root/'reports/phase5/release.json')
    config = read(root/'t2agent/text_config.json')
    require(release.get('status') == 'frozen', 'final selection is not frozen')
    require(config['mode'] == release['mode'] and config['lambda'] == release['lambda'],
            'runtime text config differs from final selection')
    for name, expected in release['runtime_sha256'].items():
        require(hashlib.sha256((root/name).read_bytes()).hexdigest() == expected,
                f'runtime changed since freeze: {name}')
    expected_paths = BUILD_INPUTS | {str(p.relative_to(root)) for p in (root/'t2agent').rglob('*')
                                     if p.suffix in ('.py', '.json')}
    require(set(release['runtime_sha256']) == expected_paths, 'incomplete runtime freeze manifest')
    require((root/'LICENSE').is_file(), 'chosen code license has not been added')
    require(release['license'] in (root/'LICENSE').read_text(), 'license declaration mismatch')
    # Catch bad license metadata through the official parser before the image exists.
    make_descriptor('ghcr.io/hhwolf/agenthon-numeric-v1@sha256:'+'0'*64,
                    release['license'], uses_house=release['mode']=='labels')
    return release


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--check', action='store_true')
    p.add_argument('--image')
    p.add_argument('--team-id')
    p.add_argument('--out', type=Path, default=Path('submission.json'))
    p.add_argument('--report', type=Path, default=Path('reports/phase5/descriptor-validation.json'))
    args = p.parse_args(argv)
    release = release_preflight()
    if args.check:
        print('Frozen final configuration and license verified.')
        return 0
    require(args.image, '--image is required to write the descriptor')
    descriptor, status = make_descriptor(args.image, release['license'],
        uses_house=release['mode']=='labels', team_id=args.team_id)
    args.out.write_text(json.dumps(descriptor, indent=2)+'\n')
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(status, indent=2)+'\n')
    print(json.dumps(status, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
