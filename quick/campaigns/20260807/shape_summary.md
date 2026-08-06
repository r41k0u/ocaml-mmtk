# Shape campaign summary — /tmp/final/20260807

### D1 corrected CPU budget (G = collector incl. mutator-side GC; W = program)
| bench | variant | G s | W s | fraction |
|---|---|---|---|---|
| binarytrees | vanilla o=500 | 1.98 | 1.64 | 0.546 |
| binarytrees | GenImmix T=1 | 1.74 | 2.46 | 0.413 |
| binarytrees | GenImmix T=4 | 3.34 | 2.48 | 0.573 |
| binarytrees | Bactrian T=1 | 1.99 | 2.76 | 0.419 |
| binarytrees | Bactrian T=4 | 4.07 | 2.72 | 0.599 |
| kb | vanilla o=500 | 0.19 | 1.23 | 0.136 |
| kb | GenImmix T=1 | 0.52 | 1.58 | 0.250 |
| kb | GenImmix T=4 | 0.51 | 1.60 | 0.244 |
| kb | Bactrian T=1 | 0.53 | 1.58 | 0.253 |
| kb | Bactrian T=4 | 0.58 | 1.63 | 0.265 |

### D3 binarytrees: MMU (authoritative stall streams)
| variant | stalls | stalled s | MMU@1ms | MMU@10ms | MMU@100ms |
|---|---|---|---|---|---|
| vanilla | 3553 | 1.98 | 0.000 | 0.000 | 0.063 |
| GenImmix | 57 | 1.25 | 0.000 | 0.000 | 0.000 |
| Bactrian | 59 | 1.01 | 0.000 | 0.000 | 0.000 |

### D3 kb: MMU (authoritative stall streams)
| variant | stalls | stalled s | MMU@1ms | MMU@10ms | MMU@100ms |
|---|---|---|---|---|---|
| vanilla | 1884 | 0.19 | 0.200 | 0.768 | 0.852 |
| GenImmix | 28 | 0.51 | 0.000 | 0.000 | 0.527 |
| Bactrian | 31 | 0.51 | 0.000 | 0.000 | 0.557 |

### M1 par_binarytrees domain sweep
| variant | d | wall s | total CPU s | GCs | stalled s |
|---|---|---|---|---|---|
| vanilla | 1 | 4.29 | 4.28 | - | 2.58 |
| vanilla | 2 | 2.66 | 5.00 | - | 1.57 |
| vanilla | 4 | 2.08 | 5.62 | - | 1.13 |
| vanilla | 8 | 1.7850000000000001 | 7.12 | - | 0.89 |
| GenImmix | 1 | 4.3681 | 4.39 | 57 | 1.79 |
| GenImmix | 2 | 2.5227 | 4.17 | 46 | 0.87 |
| GenImmix | 4 | 1.8995 | 4.78 | 56 | 0.98 |
| GenImmix | 8 | 2.6044 | 14.87 | 83 | 2.00 |
| Bactrian | 1 | 4.2231 | 4.77 | 57 | 1.25 |
| Bactrian | 2 | 2.4185 | 4.63 | 45 | 0.74 |
| Bactrian | 4 | 1.982 | 6.46 | 60 | 0.81 |
| Bactrian | 8 | 2.6404 | 17.17 | 91 | 1.96 |

### Tweak matrix (shape/tweaks): matching vanilla's pacing, and its price
| bench | nursery | cadence | GCs | STW ms | wall s | corrected G |
|---|---|---|---|---|---|---|
| binarytrees | default | 28 | 58 | 1103 | 3.64 | 3.02 |
| binarytrees | default | 64 | 58 | 1124 | 3.60 | 2.92 |
| binarytrees | default | 8 | 59 | 981 | 3.80 | 3.87 |
| binarytrees | 32MiB | 64 | 115 | 1977 | 4.63 | 5.97 |
| binarytrees | 32MiB | 8 | 116 | 1897 | 5.19 | 7.96 |
| binarytrees | 32MiB | 28 | 116 | 1826 | 4.61 | 5.63 |
| binarytrees | 8MiB | 8 | 459 | 5152 | 12.15 | 24.13 |
| binarytrees | 8MiB | 28 | 459 | 5460 | 10.22 | 17.01 |
| binarytrees | 8MiB | 64 | 460 | 5410 | 9.75 | 15.67 |
| binarytrees | 2MiB | 28 | 1866 | 14525 | 24.36 | 35.86 |
| binarytrees | 2MiB | 64 | 1867 | 15153 | 23.06 | 29.72 |
| binarytrees | 2MiB | 8 | 1868 | 12993 | 32.87 | 68.84 |
| kb | default | 28 | 28 | 527 | 2.23 | 0.55 |
| kb | default | 64 | 28 | 540 | 2.23 | 0.56 |
| kb | default | 8 | 31 | 528 | 2.23 | 0.55 |
| kb | 32MiB | 28 | 58 | 1121 | 3.01 | 1.17 |
| kb | 32MiB | 64 | 59 | 1115 | 3.04 | 1.16 |
| kb | 32MiB | 8 | 64 | 1100 | 2.97 | 1.15 |
| kb | 8MiB | 64 | 233 | 1996 | 5.02 | 2.20 |
| kb | 8MiB | 28 | 237 | 1970 | 4.95 | 2.22 |
| kb | 8MiB | 8 | 255 | 1955 | 4.98 | 2.48 |
| kb | 2MiB | 64 | 952 | 2449 | 6.73 | 3.20 |
| kb | 2MiB | 28 | 970 | 2438 | 6.73 | 3.37 |
| kb | 2MiB | 8 | 1042 | 2433 | 6.89 | 4.18 |
