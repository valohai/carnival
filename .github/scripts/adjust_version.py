"""Adjust the version in `src/carnival/__init__.py` to include the current git commit hash as a local version identifier."""

import ast
import pathlib
import re
import subprocess

version_re = re.compile(r'__version__ = (".+?")')


def main():
    scripts_path = pathlib.Path(__file__).parent.parent
    version_file = scripts_path.parent / "src" / "carnival" / "__init__.py"
    commit_hash = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=scripts_path,
        text=True,
    ).strip()
    found = False

    def replace(m):
        nonlocal found
        found = True
        current_version = ast.literal_eval(m.group(1)).partition("+")[0]
        return f'__version__ = "{current_version}+{commit_hash}"'

    text = version_re.sub(replace, version_file.read_text(), 1)
    if not found:
        raise ValueError(f"Could not find version in {version_file}")

    version_file.write_text(text)
    print(f"Updated {version_file}: to {text.strip()}")


if __name__ == "__main__":
    main()
