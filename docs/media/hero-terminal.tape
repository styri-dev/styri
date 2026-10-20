Output term.mp4  

Set Shell "bash"
Set FontFamily "JetBrains Mono"
Set FontSize 15
Set LineHeight 1.35
Set Width 560
Set Height 620
Set Padding 24
Set Framerate 20
Set TypingSpeed 28ms
Set CursorBlink false
Set Theme { "name": "styri", "background": "#0e1013", "foreground": "#e9ecef", "cursor": "#5fb4f0", "selection": "#2a3038", "black": "#0e1013", "red": "#ef6b5a", "green": "#5fcf8a", "yellow": "#f0c64a", "blue": "#5fb4f0", "magenta": "#b48ef0", "cyan": "#5fd0d6", "white": "#c9cfd6", "brightBlack": "#6c7580", "brightRed": "#ff8a7a", "brightGreen": "#7fe3a5", "brightYellow": "#ffd76a", "brightBlue": "#82c8ff", "brightMagenta": "#cbaaff", "brightCyan": "#84e6ea", "brightWhite": "#ffffff" }

Hide
Type `export PS1='\[\e[38;5;245m\]$ \[\e[0m\]'` Enter
Type `fault() { docker exec robot /ros_entrypoint.sh python3 -m styri_sim fault "$@"; }` Enter
Type `python3 -c 'import time; print(time.time())' > term.start; clear` Enter
Show

Type "# Styri, on the robot's network"
Sleep 300ms
Enter
Type "docker run --rm -d --name styri --network host ghcr.io/styri-dev/styri-core:v0.2.0 >/dev/null"
Enter
Sleep 2.6s
Type "# start the robot"
Enter
Type "docker run --rm -d --name robot --network host styri-sim >/dev/null"
Enter
Sleep 3.2s
Type "# its battery runs low"
Enter
Type "fault battery:18"
Enter
Sleep 5.5s
