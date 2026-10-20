"""python3 -m styri_sim                 run the simulated robot
python3 -m styri_sim fault <name>    inject a fault (battery:<percent>, overheat,
                                         motor_fault, battery_sag, silence:<s>, clear)
python3 -m styri_sim pose            print pose and speed as JSON"""

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from .node import print_pose, run, send_fault  # noqa: E402  (after logging setup)

if len(sys.argv) == 3 and sys.argv[1] == "fault":
    send_fault(sys.argv[2])
elif sys.argv[1:] == ["pose"]:
    print_pose()
elif len(sys.argv) == 1:
    run()
else:
    sys.exit(__doc__)
