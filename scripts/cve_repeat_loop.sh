#!/bin/bash
LOG=/lab/evidence/rep20.log
: > $LOG
for i in $(seq 1 10); do
  echo "=== ATTEMPT $i ===" >> $LOG
  /lab/run_cve_rep.sh 5 300 >> $LOG 2>&1
  D=$(ls -dt /lab/evidence/cve-rep-d5-20* | head -1)
  bad=0
  for d in "$D"/CVE-*-depth5; do
    [ "$(cat "$d/exit-code.txt" 2>/dev/null)" = "0" ] || bad=1
    grep -q "Total Error Interleavings" "$d/footer.txt" 2>/dev/null || bad=1
  done
  n=$(ls "$D" 2>/dev/null | grep -c depth5)
  if [ "$bad" -eq 0 ] && [ "$n" -eq 10 ]; then
    echo "CLEAN  $D" >> $LOG
  else
    echo "INCOMPLETE $D" >> $LOG
  fi
done
echo "REP20_LOOP_DONE" >> $LOG
