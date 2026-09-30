import subprocess


for cmd in (  # type: str
    "sudo apt update",
    "sudo apt upgrade",
    "sudo apt install nodejs",
    "sudo apt install npm",
    "sudo npm install",
    "sudo reboot"
):
    command = cmd.strip()
    if not command or command.startswith("#"):
        continue
    subprocess.run(command.split())
