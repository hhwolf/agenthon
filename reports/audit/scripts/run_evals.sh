#!/bin/bash
# Independent audit reproduction; writes only under .context/audit.
set -u
cd "$(dirname "$0")/../../.."
P=.venv/bin/python
A=.context/audit/eval-A; N=.context/audit/eval-N
L=.context/audit/logs; mkdir -p $A $N $L
unset QFBENCH_SEED TEXT_LAYER_MODE TEXT_LAYER_LAMBDA
$P -m t2eval.cli generate --work $A > $L/generate.log 2>&1
$P -m t2eval.cli eval-practice --forecaster m0 --work $A > $L/practice-m0-500.log 2>&1
for d in union practice; do ln -sfn ../eval-A/$d $N/$d; done
for s in $A/synthetic-*; do ln -sfn ../eval-A/$(basename $s) $N/$(basename $s); done
run() { name=$1; shift; "$@" > $L/$name.log 2>&1; echo "$name exit=$?" >> $L/status.txt; }
run backtest-m0-500   $P -m t2eval.cli backtest --forecaster m0 --work $A &
run backtest-m0-2000  $P -m t2eval.cli backtest --forecaster m0 --n-draws 2000 --work $A &
run backtest-v1       $P -m t2eval.cli backtest --forecaster numeric_v1 --work $A &
run backtest-v11      $P -m t2eval.cli backtest --forecaster numeric_v1_1 --work $A &
run practice-m0-2000  $P -m t2eval.cli eval-practice --forecaster m0 --n-draws 2000 --work $A &
run practice-final    $P -m t2eval.cli eval-practice --forecaster numeric_v1_1 --work $A &
run admiss-final      $P -m t2eval.cli admissibility --forecaster numeric_v1_1 --work $A &
run practice-v1-numeric env TEXT_LAYER_MODE=numeric_only $P -m t2eval.cli eval-practice --forecaster numeric_v1 --work $N &
run practice-v11-numeric env TEXT_LAYER_MODE=numeric_only $P -m t2eval.cli eval-practice --forecaster numeric_v1_1 --work $N &
wait
echo ALLDONE >> $L/status.txt
