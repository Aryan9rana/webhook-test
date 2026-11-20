#!/usr/bin/env python3
"""
Collects EC2 metadata and CloudWatch metrics for instances in a given AWS region
and saves the output to a clean, human-readable CSV report.
"""

import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

METRICS_LIST = [
    'CPUUtilization',
    'NetworkIn',
    'NetworkOut',
    'DiskReadBytes',
    'DiskWriteBytes',
    'StatusCheckFailed'
]

CSV_HEADERS = [
    'Name',
    'State',
    'Instance ID',
    'Instance Type',
    'Public IP',
    'Private IP',
    'Availability Zone',
    'Launch Time (UTC)',
    'CPU Avg (%)',
    'CPU Max (%)',
    'Net In Avg (MB)',
    'Net In Max (MB)',
    'Net Out Avg (MB)',
    'Net Out Max (MB)',
    'Disk Read (MB)',
    'Disk Write (MB)',
    'Status Check'
]


def run_aws(cmd):
    """Execute an AWS CLI command and return parsed JSON."""
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def to_mb(bytes_val):
    if bytes_val is None or bytes_val == '':
        return '-'
    return f"{float(bytes_val) / (1024 * 1024):.2f} MB"


def to_pct(pct_val):
    if pct_val is None or pct_val == '':
        return '-'
    return f"{float(pct_val):.2f}%"


def format_launch_time(iso_str):
    if not iso_str:
        return '-'
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime('%Y-%m-%d %H:%M')
    except Exception:
        return iso_str[:16].replace('T', ' ')


def parse_arguments():
    parser = argparse.ArgumentParser(description="Collect EC2 metadata and CloudWatch metrics as human-readable CSV.")
    parser.add_argument(
        '--region',
        default=os.environ.get('AWS_REGION', 'us-east-1'),
        help="AWS region (default: AWS_REGION env var or 'us-east-1')"
    )
    parser.add_argument(
        '--build-number',
        default=os.environ.get('BUILD_NUMBER', 'local'),
        help="Jenkins build number or identifier (default: BUILD_NUMBER env var or 'local')"
    )
    parser.add_argument(
        '--output',
        default=None,
        help="Output CSV filename (default: ec2-report-python-<build_number>.csv)"
    )
    return parser.parse_args()


def main():
    args = parse_arguments()
    region = args.region
    build_num = args.build_number
    output_filename = args.output or f"ec2-report-python-{build_num}.csv"

    now = datetime.now(timezone.utc)
    start_time = (now - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    end_time = now.strftime('%Y-%m-%dT%H:%M:%SZ')

    print(f"Querying EC2 instances in region: {region}...")
    try:
        ec2_data = run_aws(['aws', 'ec2', 'describe-instances', '--region', region, '--output', 'json'])
    except subprocess.CalledProcessError as err:
        print(f"Error executing AWS CLI: {err.stderr}", file=sys.stderr)
        sys.exit(1)

    rows = []

    for res in ec2_data.get('Reservations', []):
        for inst in res.get('Instances', []):
            inst_id = inst['InstanceId']
            tags = {t['Key']: t['Value'] for t in inst.get('Tags', [])}
            state = inst.get('State', {}).get('Name', '-')

            metrics = {}
            if state == 'running':
                for metric in METRICS_LIST:
                    try:
                        cw_data = run_aws([
                            'aws', 'cloudwatch', 'get-metric-statistics',
                            '--region', region,
                            '--namespace', 'AWS/EC2',
                            '--metric-name', metric,
                            '--dimensions', f'Name=InstanceId,Value={inst_id}',
                            '--start-time', start_time,
                            '--end-time', end_time,
                            '--period', '3600',
                            '--statistics', 'Average', 'Maximum',
                            '--output', 'json'
                        ])
                        datapoints = cw_data.get('Datapoints', [])
                        if datapoints:
                            dp = datapoints[0]
                            metrics[metric] = {
                                'Average': dp.get('Average'),
                                'Maximum': dp.get('Maximum')
                            }
                    except subprocess.CalledProcessError as err:
                        print(f"Warning: Failed to fetch metric {metric} for instance {inst_id}: {err.stderr.strip()}", file=sys.stderr)

            # Format status check
            status_info = metrics.get('StatusCheckFailed', {})
            status_avg = status_info.get('Average')
            if status_avg is not None:
                status_str = 'Healthy' if float(status_avg) == 0.0 else f'Failed ({status_avg})'
            else:
                status_str = '-'

            cpu_info = metrics.get('CPUUtilization', {})
            netin_info = metrics.get('NetworkIn', {})
            netout_info = metrics.get('NetworkOut', {})
            diskr_info = metrics.get('DiskReadBytes', {})
            diskw_info = metrics.get('DiskWriteBytes', {})

            row = {
                'Name': tags.get('Name', '-'),
                'State': state,
                'Instance ID': inst_id,
                'Instance Type': inst.get('InstanceType', '-'),
                'Public IP': inst.get('PublicIpAddress', '-'),
                'Private IP': inst.get('PrivateIpAddress', '-'),
                'Availability Zone': inst.get('Placement', {}).get('AvailabilityZone', '-'),
                'Launch Time (UTC)': format_launch_time(inst.get('LaunchTime')),
                'CPU Avg (%)': to_pct(cpu_info.get('Average')),
                'CPU Max (%)': to_pct(cpu_info.get('Maximum')),
                'Net In Avg (MB)': to_mb(netin_info.get('Average')),
                'Net In Max (MB)': to_mb(netin_info.get('Maximum')),
                'Net Out Avg (MB)': to_mb(netout_info.get('Average')),
                'Net Out Max (MB)': to_mb(netout_info.get('Maximum')),
                'Disk Read (MB)': to_mb(diskr_info.get('Average')),
                'Disk Write (MB)': to_mb(diskw_info.get('Average')),
                'Status Check': status_str
            }
            rows.append(row)

    with open(output_filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Successfully saved human-readable CSV report for {len(rows)} instances to {output_filename}")


if __name__ == '__main__':
    main()
