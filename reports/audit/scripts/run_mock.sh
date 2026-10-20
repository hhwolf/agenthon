#!/bin/bash
# Audit mock-final matrix. Writes only under .context/audit.
set -u
cd /Users/henryhe/conductor/workspaces/agenthon/louisville
export DOCKER_HOST=$(cat .context/audit/docker_host.txt)
EMPTY=$(mktemp -d /tmp/audit-empty-docker-config.XXXX); export DOCKER_CONFIG=$EMPTY
unset QFBENCH_SEED TEXT_LAYER_MODE TEXT_LAYER_LAMBDA
P=.venv/bin/python; M=.context/audit/mock; L=.context/audit/logs; mkdir -p $M
ROSTER=$(ls -d .context/audit/eval-A/runs/eval-practice-m0-54b*)/roster.json
PUB=ghcr.io/hhwolf/agenthon-numeric-v1@sha256:f3ec5167b28f0172004a78e336d84a4ecd423d27da42d942693e51cfc085c507
REPLAY=.context/audit/empty-replay
mf() { name=$1; shift; s=$(date +%s); $P -m t2eval.mock_final --proxy-roster $ROSTER --out $M/$name "$@" > $L/mock-$name.log 2>&1; echo "$name exit=$? secs=$(( $(date +%s)-s ))" >> $L/mock-status.txt; }
# Cold anonymous pull of the public fallback digest: remove only that cached digest first.
docker image rm $PUB >> $L/mock-rmi.log 2>&1
echo "DOCKER_CONFIG=$EMPTY contents: $(ls -A $EMPTY | wc -l) files" >> $L/mock-status.txt
mf pub-offline        --image $PUB --units practice --network none --pull-policy always
mf pub-canned         --image $PUB --units practice --network restricted --house-mode canned
mf pub-chaos          --image $PUB --units practice --network restricted --house-mode chaos
mf pub-replay         --image $PUB --units practice --network restricted --house-mode replay --replay-dir $REPLAY
mf fin-offline        --image audit-final:ee31323 --allow-local-image --units practice --network none
mf fin-canned         --image audit-final:ee31323 --allow-local-image --units practice --network restricted --house-mode canned
mf fin-chaos          --image audit-final:ee31323 --allow-local-image --units practice --network restricted --house-mode chaos
mf fin-replay         --image audit-final:ee31323 --allow-local-image --units practice --network restricted --house-mode replay --replay-dir $REPLAY
mf fin-offline-repeat --image audit-final:ee31323 --allow-local-image --units practice --network none
mf fin-seed-a         --image audit-final:ee31323 --allow-local-image --units practice --network none --seed 1111
mf fin-seed-b         --image audit-final:ee31323 --allow-local-image --units practice --network none --seed 2222
# Informational: LLM-labels variant (not the frozen candidate) under canned and chaos House.
DOCKER_CONFIG=$PWD/.context/docker-config docker buildx build --platform linux/amd64 --load -t audit-labels:ee31323 .context/audit/labels-img > $L/docker-build-labels.log 2>&1
mf lab-canned         --image audit-labels:ee31323 --allow-local-image --units practice --network restricted --house-mode canned
mf lab-chaos          --image audit-labels:ee31323 --allow-local-image --units 12 --network restricted --house-mode chaos --no-proxy-scores
echo ALLDONE >> $L/mock-status.txt
