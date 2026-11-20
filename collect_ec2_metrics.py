#!/usr/bin/env python3
"""
Collects EC2 metadata and CloudWatch metrics for instances in a given AWS region
and saves the output to a JSON report.
"""

import argparse
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


def run_aws(cmd):
    """Execute an AWS CLI command and return parsed JSON."""
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def parse_arguments():
    parser = argparse.ArgumentParser(description="Collect EC2 metadata and CloudWatch metrics.")
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
        help="Output JSON filename (default: ec2-report-python-<build_number>.json)"
    )
    return parser.parse_args()


def main():
    args = parse_arguments()
    region = args.region
    build_num = args.build_number
    output_filename = args.output or f"ec2-report-python-{build_num}.json"

    now = datetime.now(timezone.utc)
    start_time = (now - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    end_time = now.strftime('%Y-%m-%dT%H:%M:%SZ')

    print(f"Querying EC2 instances in region: {region}...")
    try:
        ec2_data = run_aws(['aws', 'ec2', 'describe-instances', '--region', region, '--output', 'json'])
    except subprocess.CalledProcessError as err:
        print(f"Error executing AWS CLI: {err.stderr}", file=sys.stderr)
        sys.exit(1)

    report = {
        'GeneratedAtUTC': end_time,
        'Region': region,
        'Instances': []
    }

    for res in ec2_data.get('Reservations', []):
        for inst in res.get('Instances', []):
            inst_id = inst['InstanceId']
            tags = {t['Key']: t['Value'] for t in inst.get('Tags', [])}
            state = inst.get('State', {}).get('Name')

            metrics_summary = {}
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
                            metrics_summary[metric] = {
                                'Average': round(dp.get('Average', 0), 4),
                                'Maximum': round(dp.get('Maximum', 0), 4),
                                'Unit': dp.get('Unit')
                            }
                        else:
                            metrics_summary[metric] = None
                    except subprocess.CalledProcessError as err:
                        print(f"Warning: Failed to fetch metric {metric} for instance {inst_id}: {err.stderr.strip()}", file=sys.stderr)
                        metrics_summary[metric] = None

            report['Instances'].append({
                'InstanceId': inst_id,
                'Name': tags.get('Name'),
                'State': state,
                'InstanceType': inst.get('InstanceType'),
                'LaunchTime': inst.get('LaunchTime'),
                'PrivateIP': inst.get('PrivateIpAddress'),
                'PublicIP': inst.get('PublicIpAddress'),
                'AvailabilityZone': inst.get('Placement', {}).get('AvailabilityZone'),
                'MetricsLast1Hour': metrics_summary
            })

    with open(output_filename, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Successfully saved report for {len(report['Instances'])} instances to {output_filename}")


if __name__ == '__main__':
    main()
