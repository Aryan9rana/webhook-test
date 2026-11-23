#!/usr/bin/env python3
"""
Collects EC2 metadata and CloudWatch metrics for instances in a given AWS region
and saves the output to a clean, human-readable CSV report using Boto3 (AWS SDK for Python).
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError

METRICS_LIST = [
    'CPUUtilization',
    'NetworkIn',
    'NetworkOut',
    'EBSReadBytes',
    'EBSWriteBytes',
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
    'EBS Read (MB)',
    'EBS Write (MB)',
    'Status Check'
]


def to_mb(bytes_val):
    if bytes_val is None or bytes_val == '':
        return '-'
    return f"{float(bytes_val) / (1024 * 1024):.2f} MB"


def to_pct(pct_val):
    if pct_val is None or pct_val == '':
        return '-'
    return f"{float(pct_val):.2f}%"


def format_launch_time(dt_val):
    if not dt_val:
        return '-'
    if isinstance(dt_val, datetime):
        return dt_val.strftime('%Y-%m-%d %H:%M')
    try:
        dt = datetime.fromisoformat(str(dt_val))
        return dt.strftime('%Y-%m-%d %H:%M')
    except Exception:
        return str(dt_val)[:16].replace('T', ' ')


def parse_arguments():
    parser = argparse.ArgumentParser(description="Collect EC2 metadata and CloudWatch metrics as human-readable CSV using Boto3.")
    parser.add_argument(
        '--region',
        default=os.environ.get('AWS_REGION', 'us-east-1'),
        help="AWS region (default: AWS_REGION env var or 'us-east-1')"
    )
    parser.add_argument(
        '--build-number',
        default=os.environ.get('CSV_BUILD_NUMBER') or os.environ.get('BUILD_NUMBER') or 'local',
        help="Jenkins CSV build number or identifier (default: CSV_BUILD_NUMBER / BUILD_NUMBER env var or 'local')"
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
    start_time = now - timedelta(hours=1)
    end_time = now

    print(f"Querying EC2 instances in region: {region} via Boto3...")
    try:
        ec2 = boto3.client('ec2', region_name=region)
        cw = boto3.client('cloudwatch', region_name=region)
        paginator = ec2.get_paginator('describe_instances')
        page_iterator = paginator.paginate()
    except (ClientError, BotoCoreError) as err:
        print(f"Error initializing Boto3 client: {err}", file=sys.stderr)
        sys.exit(1)

    rows = []

    try:
        for page in page_iterator:
            for res in page.get('Reservations', []):
                for inst in res.get('Instances', []):
                    inst_id = inst['InstanceId']
                    tags = {t['Key']: t['Value'] for t in inst.get('Tags', [])}
                    state = inst.get('State', {}).get('Name', '-')

                    metrics = {}
                    if state == 'running':
                        for metric in METRICS_LIST:
                            try:
                                cw_data = cw.get_metric_statistics(
                                    Namespace='AWS/EC2',
                                    MetricName=metric,
                                    Dimensions=[{'Name': 'InstanceId', 'Value': inst_id}],
                                    StartTime=start_time,
                                    EndTime=end_time,
                                    Period=3600,
                                    Statistics=['Average', 'Maximum']
                                )
                                datapoints = cw_data.get('Datapoints', [])
                                if datapoints:
                                    dp = datapoints[0]
                                    metrics[metric] = {
                                        'Average': dp.get('Average'),
                                        'Maximum': dp.get('Maximum')
                                    }
                            except (ClientError, BotoCoreError) as err:
                                print(f"Warning: Failed to fetch metric {metric} for instance {inst_id}: {err}", file=sys.stderr)

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
                    ebsr_info = metrics.get('EBSReadBytes', {})
                    ebsw_info = metrics.get('EBSWriteBytes', {})

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
                        'EBS Read (MB)': to_mb(ebsr_info.get('Average')),
                        'EBS Write (MB)': to_mb(ebsw_info.get('Average')),
                        'Status Check': status_str
                    }
                    rows.append(row)
    except (ClientError, BotoCoreError) as err:
        print(f"Error querying EC2 via Boto3: {err}", file=sys.stderr)
        sys.exit(1)

    with open(output_filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Successfully saved human-readable CSV report for {len(rows)} instances to {output_filename}")


if __name__ == '__main__':
    main()
