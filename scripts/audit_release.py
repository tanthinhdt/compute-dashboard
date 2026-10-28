#!/usr/bin/env python3
"""Check a source tree for common credentials and private deployment artifacts.

This is a repeatable heuristic audit, not a guarantee that every secret is detected.
Review all new files before publishing.
"""
import ipaddress
from pathlib import Path
import re
import sys

SKIP = {'.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache'}
BINARY = {'.ico', '.png'}
PATTERNS = {
    'private key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'GitHub token': re.compile(r'\bgh[pousr]_[A-Za-z0-9]{30,}\b'),
    'GitHub fine-grained token': re.compile(r'\bgithub_pat_[A-Za-z0-9_]{40,}\b'),
    'AWS access key': re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'absolute user home': re.compile(r'(?:/home/|/Users/)[A-Za-z0-9_.-]+/'),
    'credential URL': re.compile(r'https?://[^\s/:]+:[^\s/@]+@'),
}


def audit(root):
    problems = []
    count = 0
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if set(relative.parts) & SKIP or not path.is_file():
            continue
        count += 1
        if path.is_symlink():
            problems.append((str(relative), 'symlink requires review'))
            continue
        if path.name in {'config.yaml', '.env', 'kaggle.json'} or path.suffix in {'.log', '.pid', '.key', '.pem', '.pyc'}:
            problems.append((str(relative), 'private or generated artifact'))
        if path.suffix in BINARY:
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            problems.append((str(relative), 'unreviewed binary'))
            continue
        for name, pattern in PATTERNS.items():
            if pattern.search(text):
                problems.append((str(relative), name))
        for candidate in re.findall(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])', text):
            try:
                address = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            # Loopback and RFC 5737 examples are safe source examples.
            examples = any(address in ipaddress.ip_network(net) for net in ['192.0.2.0/24', '198.51.100.0/24', '203.0.113.0/24'])
            if not address.is_loopback and not examples:
                problems.append((str(relative), 'non-example IP address'))
    return count, sorted(set(problems))


if __name__ == '__main__':
    count, problems = audit(Path(__file__).resolve().parents[1])
    for path, reason in problems:
        print(f'{path}: {reason}')
    print(f'Checked {count} files; {len(problems)} findings.')
    sys.exit(bool(problems))
