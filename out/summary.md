# Autotest Summary

- input_files: 1
- uris: 4

| uri | warmup_success_rate | eval_success_rate | eval_success_rate_when_publisher_down |
|---|---:|---:|---:|
| ccnx:/emergency | 0.000 | 0.000 | 0.000 |
| ccnx:/emergency/test | 0.000 | 0.000 | 0.000 |
| ccnx:/emergency/test2 | 0.000 | 0.000 | 0.000 |
| ccnx:/test/data1 | 0.000 | 0.000 | 0.000 |

## Failure Reasons (Eval)

| uri | exit_code_nonzero | missing_completed_log | missing_output_file |
|---|---:|---:|---:|
| ccnx:/emergency | 0 | 0 | 0 |
| ccnx:/emergency/test | 16 | 16 | 16 |
| ccnx:/emergency/test2 | 8 | 8 | 8 |
| ccnx:/test/data1 | 8 | 8 | 8 |
