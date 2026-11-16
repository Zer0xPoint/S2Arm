#!/bin/bash
# 门禁覆盖：pack/jobs/*.py pack/jobs/tests/*.py docs/site/notice.json launchers/macos/bundle_engine.py launchers/macos/s2armctl.py launchers/macos/adapter/Sources/S2ArmAppleAdapter/Resources/Localizable.json
# pack/jobs 单测整目录在同一进程里跑一次（11-16）：本单测按文件分进程并行跑（tests/pack_jobs_test.sh），看不到用例之间留下的模块状态——
#   test_install / test_early_install / test_job_failure_codes 先跑时把 push_pack 留在模块缓存，test_win_jobs 的 WinInstall 11 项因此走进真推送客户端，
#   单跑该文件 44 项全过、按文件跑的门禁一直绿。整目录跑一次就能看到这类串扰
set -u; cd "$(dirname "$0")/.." || exit 1
PACK_JOBS_SERIAL=1 exec bash tests/pack_jobs_test.sh
