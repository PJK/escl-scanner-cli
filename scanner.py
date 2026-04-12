#!/usr/bin/env python3

__version__ = '0.2.1'

import json
import os
import sys
import time
from decimal import Decimal

import papersize
import requests
import xmltodict
import zeroconf

'''
See: https://mopria.org/MopriaeSCLSpecDownload.php
'''

HTTP_TIMEOUT_SECONDS = 30

DISCOVERY_TIMEOUT_SECONDS = 30.0
DISCOVERY_RETRIES = 2
DISCOVERY_RETRY_DELAY_SECONDS = 0.5
DISCOVERY_SLEEP_SECONDS = 0.1


def parse_region(region_spec):
    '''
    Parse a region spec into a dict of ThreeHundredthsOfInches integers.
    Accepts a paper size name (e.g. 'a4') or 'Xoffset:Yoffset:Width:Height'
    with units understood by the papersize library (e.g. '1cm:1.5cm:10cm:20cm').
    Raises ValueError on invalid input.
    '''
    region_spec = region_spec.lower()
    try:
        if region_spec in papersize.SIZES:
            paper_size = papersize.parse_papersize(region_spec)
            region_decimals = {
                'x': Decimal('0'),
                'y': Decimal('0'),
                'width': paper_size[0],
                'height': paper_size[1],
            }
        else:
            parts = region_spec.split(':')
            if len(parts) != 4:
                raise papersize.CouldNotParse(region_spec)
            parsed_parts = [papersize.parse_length(p) for p in parts]
            region_decimals = {
                'x': parsed_parts[0],
                'y': parsed_parts[1],
                'width': parsed_parts[2],
                'height': parsed_parts[3],
            }
    except papersize.CouldNotParse:
        raise ValueError(f'Could not parse region: {region_spec}')

    c = papersize.UNITS['in'] / 300  # ThreeHundredthsOfInches
    return {k: int(v / c) for k, v in region_decimals.items()}


def resolve_scanner(
    timeout_seconds=DISCOVERY_TIMEOUT_SECONDS,
    retries=DISCOVERY_RETRIES,
):
    class ZCListener:
        def __init__(self):
            self.info = None

        def update_service(self, zeroconf, type, name):
            pass

        def remove_service(self, zeroconf, type, name):
            pass

        def add_service(self, zeroconf, type, name):
            self.info = zeroconf.get_service_info(type, name)

    for attempt in range(retries):
        with zeroconf.Zeroconf() as zc:
            listener = ZCListener()
            zeroconf.ServiceBrowser(zc, "_uscan._tcp.local.", listener=listener)
            deadline = time.monotonic() + timeout_seconds
            try:
                while time.monotonic() < deadline:
                    if listener.info:
                        return listener.info
                    time.sleep(DISCOVERY_SLEEP_SECONDS)
            except Exception:
                pass
        if attempt + 1 < retries:
            time.sleep(DISCOVERY_RETRY_DELAY_SECONDS)
    return None


def _get_status(session, base, job_uuid=None):
    resp = session.get(f'{base}/ScannerStatus', timeout=HTTP_TIMEOUT_SECONDS)
    resp.raise_for_status()
    status = xmltodict.parse(
        resp.text, force_list=('scan:JobInfo'))['scan:ScannerStatus']
    if job_uuid is None:
        return status, None

    uuid_prefix = "urn:uuid:"  # Seen in a Brother MFC device
    for jobinfo in status['scan:Jobs']['scan:JobInfo']:
        current_uuid = jobinfo['pwg:JobUuid']
        if current_uuid.startswith(uuid_prefix):
            current_uuid = current_uuid[len(uuid_prefix):]
        if current_uuid == job_uuid:
            return status, jobinfo
    raise RuntimeError('Job not found')


def scan(info, *, source, grayscale, resolution, duplex, output_path, region=None, debug=False):
    '''
    Perform a scan and write the result as a PDF to output_path.
    Returns True on success, False on failure.
    '''
    props = info.properties

    if duplex and props.get(b'duplex') != b'T':
        print('Duplex not supported', file=sys.stderr)
        return False

    if b'rs' not in props:
        print('Scanner did not advertise a root path (rs)', file=sys.stderr)
        return False

    session = requests.Session()

    if debug:
        print(info, file=sys.stderr)

    rs = props[b'rs'].decode()
    if rs[0] != '/':
        rs = '/' + rs
    base = f'http://{info.server}:{info.port}{rs}'

    if debug:
        print(base, file=sys.stderr)

    resp = session.get(f'{base}/ScannerCapabilities', timeout=HTTP_TIMEOUT_SECONDS)
    resp.raise_for_status()
    if debug:
        print(resp.text, file=sys.stderr)

    status, _ = _get_status(session, base)
    if status['pwg:State'] != 'Idle':
        print('Scanner is not idle', file=sys.stderr)
        return False

    source_xml = {
        'automatic': '',
        'feeder': '<pwg:InputSource>Feeder</pwg:InputSource>',
        'flatbed': '<pwg:InputSource>Platen</pwg:InputSource>',
    }[source]

    color = 'Grayscale8' if grayscale else 'RGB24'

    job = f'''<?xml version="1.0" encoding="UTF-8"?>
    <scan:ScanSettings xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03"
      xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">
      <pwg:Version>2.0</pwg:Version>
      <scan:Intent>TextAndGraphic</scan:Intent>
      <pwg:DocumentFormat>application/pdf</pwg:DocumentFormat>
      {source_xml}
      <scan:ColorMode>{color}</scan:ColorMode>
      <scan:Duplex>{str(duplex).lower()}</scan:Duplex>
      <scan:XResolution>{resolution}</scan:XResolution>
      <scan:YResolution>{resolution}</scan:YResolution>
    '''
    if region:
        job += f'''
      <pwg:ScanRegions>
        <pwg:ScanRegion>
          <pwg:ContentRegionUnits>escl:ThreeHundredthsOfInches</pwg:ContentRegionUnits>
          <pwg:XOffset>{region['x']}</pwg:XOffset>
          <pwg:YOffset>{region['y']}</pwg:YOffset>
          <pwg:Width>{region['width']}</pwg:Width>
          <pwg:Height>{region['height']}</pwg:Height>
        </pwg:ScanRegion>
      </pwg:ScanRegions>
        '''
    job += '    </scan:ScanSettings>'
    resp = session.post(f'{base}/ScanJobs', data=job, headers={'Content-Type': 'text/xml'}, timeout=HTTP_TIMEOUT_SECONDS)
    resp.raise_for_status()

    job_uri = resp.headers['location']
    job_uuid = job_uri.rstrip('/').split('/')[-1]

    try:
        # Each NextDocument response is one page (PDF). Pages are written
        # sequentially to output_path; 404 signals no more pages remain.
        while True:
            status, jobinfo = _get_status(session, base, job_uuid=job_uuid)
            if debug:
                print(json.dumps(jobinfo, indent=2), file=sys.stderr)

            retry_count = 0
            while True:
                resp = session.get(f'{job_uri}/NextDocument', timeout=HTTP_TIMEOUT_SECONDS)
                if resp.status_code != 503:
                    break
                retry_count += 1
                if debug:
                    print(f'503 from NextDocument (attempt {retry_count})', file=sys.stderr)
                if retry_count >= 100:
                    print('Scanner returned 503 for NextDocument', file=sys.stderr)
                    resp.raise_for_status()
                time.sleep(1)
            if resp.status_code == 404:
                # We are done
                break
            resp.raise_for_status()

            with open(output_path, 'wb') as f:
                f.write(resp.content)

            if status['pwg:State'] != 'Processing':
                break
            time.sleep(1)

        status, jobinfo = _get_status(session, base, job_uuid=job_uuid)
        job_reason = jobinfo['pwg:JobStateReasons']['pwg:JobStateReason']
        if debug:
            print(job_reason, file=sys.stderr)

        success = job_reason == 'JobCompletedSuccessfully'
    except Exception:
        success = False

    if not success and os.path.exists(output_path):
        os.remove(output_path)

    return success
