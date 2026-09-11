#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python3 -m venv "$project_dir/.venv"
"$project_dir/.venv/bin/python" -m pip install -r "$project_dir/requirements.txt"
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/jotline" <<EOF
#!/bin/sh
exec "$project_dir/.venv/bin/python" "$project_dir/notes.py" "\$@"
EOF
chmod +x "$HOME/.local/bin/jotline"
printf '%s\n' "Installed jotline in $HOME/.local/bin/jotline"
