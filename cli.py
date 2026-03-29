#!/usr/bin/env python3

import datetime
import os
import subprocess
import sys

import click

from scanner import __version__, resolve_scanner, scan


@click.command()
@click.version_option(version=__version__)
@click.argument('filename')
@click.option('--source', '-S', type=click.Choice(['feeder', 'flatbed', 'automatic']), default='automatic', show_default=True)
@click.option('--grayscale', '-g', is_flag=True, help='Scan in grayscale instead of RGB')
@click.option('--resolution', '-r', type=click.Choice(['75', '100', '200', '300', '600']), default='200', show_default=True)
@click.option('--duplex', '-D', is_flag=True, help='Enable duplex (double-sided) scanning')
@click.option('--today', '-t', is_flag=True, help='Prepend date to filename in ISO format')
@click.option('--no-open', '-o', 'no_open', is_flag=True, help="Don't open the PDF after scanning")
@click.option('--quiet', '-q', is_flag=True, help='Suppress scanner name output')
@click.option('--debug', '-d', is_flag=True, help='Print debugging information to stderr')
def main(filename, source, grayscale, resolution, duplex, today, no_open, quiet, debug):
    if today:
        filename = datetime.date.today().isoformat() + '-' + filename

    if not filename.endswith('.pdf'):
        raise click.UsageError('File must have a .pdf extension')

    if os.path.exists(filename):
        raise click.UsageError(f'File {filename} already exists')

    info = resolve_scanner()
    if not info:
        click.echo('No scanner found', err=True)
        sys.exit(1)

    if not quiet:
        suffix = '._uscan._tcp.local.'
        name = info.name
        if name.endswith(suffix):
            name = name[:-len(suffix)]
        click.echo(f'Using {name}')

    success = scan(
        info,
        source=source,
        grayscale=grayscale,
        resolution=int(resolution),
        duplex=duplex,
        output_path=filename,
        debug=debug,
    )

    if not success:
        sys.exit(1)

    if not no_open:
        subprocess.run(['open', filename])


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
