"""
Copyright ©️ IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from openpilot.system.athena.manage_athenad import manage_athenad
HEPHAESTUS_MGR_PID_PARAM = "HephaestusdPid"
def main():
    manage_athenad(dongle_id_param="DongleId", pid_param=HEPHAESTUS_MGR_PID_PARAM, process_name="hephaestusd", target="sunnypilot.konn3kt.athena.hephaestusd")
if __name__ == '__main__':
    main()