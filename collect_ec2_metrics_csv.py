#!/usr/bin/env python3
"""
Collects EC2 metadata and CloudWatch metrics for instances in a given AWS region
and saves the output to a CSV report.
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
    'InstanceId',
    'Name',
    'State',
    'InstanceType',
    'LaunchTime',
    'PrivateIP',
    'PublicIP',
    'AvailabilityZone',
    'CPUUtilization_Avg',
    'CPUUtilization_Max',
    'NetworkIn_Avg',
    'NetworkIn_Max',
    'NetworkOut_Avg',
    'NetworkOut_Max',
    'DiskReadBytes_Avg',
    'DiskReadBytes_Max',
    'DiskWriteBytes_Avg',
    'DiskWriteBytes_Max',
    'StatusCheckFailed_Avg',
    'StatusCheckFailed_Max'
]


def run_aws(cmd):
    """Execute an AWS CLI command and return parsed JSON."""
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def parse_arguments():
    parser = argparse.ArgumentParser(description="Collect EC2 metadata and CloudWatch metrics as CSV.")
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
            state = inst.get('State', {}).get('Name')

            row = {
                'InstanceId': inst_id,
                'Name': tags.get('Name', ''),
                'State': state,
                'InstanceType': inst.get('InstanceType', ''),
                'LaunchTime': inst.get('LaunchTime', ''),
                'PrivateIP': inst.get('PrivateIpAddress', ''),
                'PublicIP': inst.get('PublicIpAddress', ''),
                'AvailabilityZone': inst.get('Placement', {}).get('AvailabilityZone', '')
            }

            for metric in METRICS_LIST:
                avg_val = ''
                max_val = ''
                if state == 'running':
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
                            avg_val = round(dp.get('Average', 0), 4)
                            max_val = round(dp.get('Maximum', 0), 4)
                    except subprocess.CalledProcessError as err:
                        print(f"Warning: Failed to fetch metric {metric} for instance {inst_id}: {err.stderr.strip()}", file=sys.stderr)

                row[f"{metric}_Avg"] = avg_val
                row[f"{metric}_Max"] = max_val

            rows.append(row)

    with open(output_filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Successfully saved CSV report for {len(rows)} instances to {output_filename}")


if __name__ == '__main__':
    main()
