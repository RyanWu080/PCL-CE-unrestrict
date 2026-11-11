"""Read the SDK requested by an upstream commit and select the installed SDK."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

WORKFLOW = '.github/workflows/reusable-build.yml'
EXACT = r'\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+(?:[.-][a-zA-Z0-9]+)*)?'
REQUEST = rf'(?:{EXACT}|\d+\.\d+\.x|\d+\.\d+)'


def sdk_input(workflow, key, allowed, optional=False):
    values = re.findall(rf'^ +{key}: *(.*?)\s*$', workflow, re.MULTILINE)
    if not values and optional:
        return ''
    if len(values) == 1:
        value = values[0].split('#', 1)[0].strip()
        if len(value) > 1 and value[0] in ("'", '"') and value[-1] == value[0]:
            value = value[1:-1]
        if re.fullmatch(allowed, value):
            return value
    raise ValueError(f'Expected one supported literal {key} in upstream {WORKFLOW}')


def resolve(ref, source):
    workflow = subprocess.check_output(['git', 'show', f'{ref}:{WORKFLOW}'],
                                       cwd=source, encoding='utf-8')
    version = sdk_input(workflow, 'dotnet-version', REQUEST)
    quality = sdk_input(workflow, 'dotnet-quality', 'ga|preview|daily|signed|validated', optional=True)
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        output.write(f'version={version}\nquality={quality}\n')
    print(f'Upstream {ref} requests .NET SDK {version}')


def pin(version, source):
    if not re.fullmatch(EXACT, version):
        raise ValueError('Expected an exact installed .NET SDK version')
    # A repository-provided global.json remains authoritative.
    path = source / 'global.json'
    if not path.exists():
        path.write_text(json.dumps({'sdk': {'version': version, 'rollForward': 'disable'}}),
                        encoding='utf-8')
    actual = subprocess.check_output(['dotnet', '--version'], cwd=source, text=True).strip()
    if actual != version:
        raise RuntimeError(f'Repository resolved SDK {actual}, expected installed SDK {version}')
    print(f'Build will use .NET SDK {actual}')


if __name__ == '__main__':
    command, value, *directory = sys.argv[1:]
    source = Path(directory[0]) if directory else Path.cwd()
    if command == 'resolve':
        resolve(value, source)
    elif command == 'pin':
        pin(value, source)
    else:
        raise ValueError(f'Unknown SDK command: {command}')
