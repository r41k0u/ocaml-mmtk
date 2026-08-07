# Shape campaign summary — /tmp/p3/phase3

### D1 corrected CPU budget, all benches (T=1; G = collector incl. mutator-side GC)
| bench | variant | G s | W s | fraction |
|---|---|---|---|---|
| LU_decomposition | vanilla | 0.01 | 1.67 | 0.004 |
| LU_decomposition | Bactrian | 0.22 | 2.14 | 0.093 |
| binarytrees | vanilla | 1.97 | 1.65 | 0.544 |
| binarytrees | Bactrian | 1.73 | 2.54 | 0.405 |
| fannkuchredux | vanilla | 0.00 | 3.32 | 0.000 |
| fannkuchredux | Bactrian | 0.00 | 3.41 | 0.000 |
| kb | vanilla | 0.19 | 1.22 | 0.138 |
| kb | Bactrian | 0.29 | 1.41 | 0.170 |
| mandelbrot | vanilla | 0.00 | 1.76 | 0.000 |
| mandelbrot | Bactrian | 0.00 | 1.69 | 0.000 |
| matrix_multiplication | vanilla | 0.00 | 1.46 | 0.001 |
| matrix_multiplication | Bactrian | 0.04 | 2.77 | 0.016 |
| nbody | vanilla | 0.00 | 2.09 | 0.000 |
| nbody | Bactrian | 0.00 | 2.09 | 0.000 |
| spectralnorm | vanilla | 0.00 | 1.53 | 0.003 |
| spectralnorm | Bactrian | 0.10 | 1.67 | 0.055 |

### D3 binarytrees: MMU (authoritative stall streams)
| variant | stalls | stalled s | MMU@1ms | MMU@10ms | MMU@100ms |
|---|---|---|---|---|---|
| vanilla | 3553 | 1.97 | 0.000 | 0.000 | 0.063 |
| Bactrian | 57 | 1.05 | 0.000 | 0.000 | 0.000 |

### D3 kb: MMU (authoritative stall streams)
| variant | stalls | stalled s | MMU@1ms | MMU@10ms | MMU@100ms |
|---|---|---|---|---|---|
| vanilla | 1884 | 0.19 | 0.193 | 0.763 | 0.851 |
| Bactrian | 31 | 0.26 | 0.000 | 0.000 | 0.699 |

### M1 par_binarytrees domain sweep
| variant | d | wall s | total CPU s | GCs | stalled s |
|---|---|---|---|---|---|
| vanilla | 1 | 4.275 | 4.26 | - | 2.58 |
| vanilla | 2 | 2.3499999999999996 | 4.29 | - | 1.29 |
| vanilla | 4 | 1.59 | 4.37 | - | 0.93 |
| vanilla | 8 | 1.18 | 5.00 | - | 0.64 |
| GenImmix | 1 | - | - | - | - |
| GenImmix | 2 | - | - | - | - |
| GenImmix | 4 | - | - | - | - |
| GenImmix | 8 | - | - | - | - |
| Bactrian | 1 | 3.7524 | 4.28 | 57 | 1.09 |
| Bactrian | 2 | 2.1398 | 4.00 | 45 | 0.58 |
| Bactrian | 4 | 1.6162 | 5.36 | 51 | 0.72 |
| Bactrian | 8 | 2.4759 | 17.00 | 82 | 1.75 |

### Hardware counters, whole process (Bactrian / vanilla ratios)
| bench | instructions | cycles | LLC-loads |
|---|---|---|---|
| LU_decomposition | 1.06x | 1.41x | 1.18x |
| binarytrees | 0.84x | 1.17x | 1.34x |
| fannkuchredux | 1.00x | 1.03x | 1.64x |
| kb | 1.03x | 1.19x | 1.43x |
| mandelbrot | 1.00x | 0.97x | 1.60x |
| matrix_multiplication | 1.01x | 1.84x | 12.26x |
| nbody | 1.00x | 1.00x | 1.50x |
| spectralnorm | 1.04x | 1.16x | 1.17x |

### Hybrid perf D1 (worker threads = G by identity; mutator by symbol)
| bench | vanilla G share | Bactrian G share |
|---|---|---|
| LU_decomposition | 0.001 | 0.029 |
| binarytrees | 0.500 | 0.391 |
| kb | 0.136 | 0.160 |
| matrix_multiplication | 0.003 | 0.005 |
