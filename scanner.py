#!/usr/bin/env python3

import json
import sys
import time

import requests
import xmltodict
import zeroconf

'''
See: https://mopria.org/MopriaeSCLSpecDownload.php
'''


def resolve_scanner():
    class ZCListener:
        def __init__(self):
            self.info = None

        def update_service(self, zeroconf, type, name):
            pass

        def remove_service(self, zeroconf, type, name):
            pass

        def add_service(self, zeroconf, type, name):
            self.info = zeroconf.get_service_info(type, name)

    with zeroconf.Zeroconf() as zc:
        listener = ZCListener()
        zeroconf.ServiceBrowser(zc, "_uscan._tcp.local.", listener=listener)
        try:
            for i in range(0, 10 * 10):
                if listener.info:
                    break
                time.sleep(.1)
        except Exception:
            pass
    return listener.info


def _get_status(session, base, job_uuid=None):
    resp = session.get(f'{base}/ScannerStatus')
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


def scan(info, *, source, grayscale, resolution, duplex, output_path, debug=False):
    '''
    Perform a scan and write the result as a PDF to output_path.
    Returns True on success, False on failure.
    '''
    props = info.properties

    if duplex and props.get(b'duplex') != b'T':
        print('Duplex not supported', file=sys.stderr)
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

    resp = session.get(f'{base}/ScannerCapabilities')
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
        'flatbed': '<pwg:InputSource>Flatbed</pwg:InputSource>',
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
    </scan:ScanSettings>
    '''
    resp = session.post(f'{base}/ScanJobs', data=job, headers={'Content-Type': 'text/xml'})
    resp.raise_for_status()

    job_uri = resp.headers['location']
    job_uuid = job_uri.rstrip('/').split('/')[-1]

    while True:
        status, jobinfo = _get_status(session, base, job_uuid=job_uuid)
        if debug:
            print(json.dumps(jobinfo, indent=2), file=sys.stderr)

        resp = session.get(f'{job_uri}/NextDocument')
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

    return job_reason == 'JobCompletedSuccessfully'
