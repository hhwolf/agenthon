# Mock Final digest comparison

A: `ghcr.io/hhwolf/agenthon-numeric-v1@sha256:25ffda44821a0493ba5ba69aeb570ec009a5e1081cd54d5e615fa3d51ac70a01`
B: `ghcr.io/hhwolf/agenthon-numeric-v1@sha256:f3ec5167b28f0172004a78e336d84a4ecd423d27da42d942693e51cfc085c507`

| Metric | A | B |
|---|---:|---:|
| units | 104 | 104 |
| statuses | {'passed': 104} | {'passed': 104} |
| proxy_units | 88 | 88 |
| proxy_mean | 2.4357406110104836 | 2.4157440633855654 |
| caps | 9 | 9 |
| requests_used | 0 | 0 |
| ingestion_seconds | 145.07134579203557 | 157.30602062505204 |
| projection_104_seconds | 145.0231001257198 | 157.25847975048237 |
| over_half_platform_clock | False | False |

Paired mean B − A: -0.019996547624918606 (88 units).
Scores are local practice proxies. Successful units without labels have no score.
Pull time is measured; a cached pull is not a cold layer download.
