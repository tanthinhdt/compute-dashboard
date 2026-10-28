#!/usr/bin/env python3
"""Read dashboard observations using only Python's standard library."""
import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def query_resources(resource_type=None, min_free_vram_gb=0, min_available_ram_gb=0, max_gpu_util_pct=20):
    base = os.environ.get('COMPUTE_DASHBOARD_URL', 'http://127.0.0.1:8080').rstrip('/')
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('COMPUTE_DASHBOARD_URL must be an HTTP(S) base URL without credentials or query parameters')
    token = os.environ.get('COMPUTE_DASHBOARD_API_TOKEN', '')
    if token and parsed.scheme != 'https' and parsed.hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise ValueError('Use HTTPS or a localhost tunnel when sending an API token')
    if resource_type not in {None, 'gpu', 'cpu', 'workstation', 'kaggle'}:
        raise ValueError('Invalid resource type')
    if min_free_vram_gb < 0 or min_available_ram_gb < 0 or not 0 <= max_gpu_util_pct <= 100:
        raise ValueError('Invalid resource thresholds')
    params = dict(min_free_vram_gb=min_free_vram_gb,
                  min_available_ram_gb=min_available_ram_gb, max_gpu_util_pct=max_gpu_util_pct)
    if resource_type:
        params['resource_type'] = resource_type
    headers = {'Accept': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    request = urllib.request.Request(base + '/api/v1/resources?' + urllib.parse.urlencode(params), headers=headers)
    with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
        result = json.load(response)
    if result.get('schema_version') != '1.0' or not isinstance(result.get('resources'), list):
        raise ValueError('Unsupported resource response')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resource-type', choices=['gpu', 'cpu', 'workstation', 'kaggle'])
    parser.add_argument('--min-free-vram-gb', type=float, default=0)
    parser.add_argument('--min-available-ram-gb', type=float, default=0)
    parser.add_argument('--max-gpu-util-pct', type=float, default=20)
    args = parser.parse_args()
    try:
        print(json.dumps(query_resources(**vars(args)), indent=2))
    except (OSError, ValueError, urllib.error.URLError):
        parser.exit(1, 'Cannot query the dashboard. Check its URL, network access, token, and response version.\n')


if __name__ == '__main__':
    main()
