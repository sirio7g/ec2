#!/usr/bin/env python
from __future__ import print_function

import boto3
import json
import argparse
import sys
import time
import traceback
import getopt

elb_name = None
asg_name = None
client_elb = None
client = None
assume_yes = False

def exit(message):
	print(message, file=sys.stderr)
	sys.exit(1)

# Copyied from StackOverflow
def query_yes_no(question, default="yes"):
    """Ask a yes/no question via raw_input() and return their answer.

    "question" is a string that is presented to the user.
    "default" is the presumed answer if the user just hits <Enter>.
        It must be "yes" (the default), "no" or None (meaning
        an answer is required of the user).

    The "answer" return value is True for "yes" or False for "no".
    """
    global assume_yes

    if assume_yes:
    	return True

    valid = {"yes": True, "y": True, "ye": True,
             "no": False, "n": False}
    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        sys.stdout.write(question + prompt)
        choice = raw_input().lower()
        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("Please respond with 'yes' or 'no' "
                             "(or 'y' or 'n').\n")


def print_new_state():
	global client_elb
	global client
	global elb_name
	global asg_name

	print("*** New State ***\nELB %s" % (elb_name))

	response = client_elb.describe_instance_health(LoadBalancerName=elb_name)
	for instance_health in response['InstanceStates']:
		print("InstanceId: %s (%s)" % (instance_health['InstanceId'], instance_health['State']))

	response = client.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])
	asg = response['AutoScalingGroups'][0]
	print("\nASG: %s [Max: %s, Min: %s, Desired: %s]" % (asg_name, asg['MaxSize'], asg['MinSize'], asg['DesiredCapacity']))
	for instace in asg['Instances']:
		print("InstanceId: %s (%s)" % (instace['InstanceId'], instace['AvailabilityZone']))
	print("****************")


def get_elb_from_asg_info(client, asg_name):
    response = client.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])
    elbs = response['AutoScalingGroups'][0]['LoadBalancerNames']
    desired_size = response['AutoScalingGroups'][0]['DesiredCapacity']
    max_size = response['AutoScalingGroups'][0]['MaxSize']
    actual_size = len(response['AutoScalingGroups'][0]['Instances'])
    
    if desired_size != actual_size:
    	exit("Desired capacity and actual capacity do not match. Aborting script.")

    if len(elbs) > 1:
    	exit("Found multiple ELBs attached to the AutoScalingGroup %s. This script doesn't support it. Exiting ..." % (asg_name))

    return elbs[0], desired_size, max_size


def get_instances_from_asg(client, asg_name):
    instances = []
    response = client.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])
    for instance in response['AutoScalingGroups'][0]['Instances']:
    	instances.append(instance.get('InstanceId'))

    return instances


def get_instances_in_service_from_elb(client, elb_name):
	instances = []
	response = client.describe_instance_health(LoadBalancerName=elb_name)
	for instance_health in response['InstanceStates']:
		if instance_health['State'] == 'InService':
			print("Found instance %s in service on ELB %s" % (instance_health['InstanceId'], elb_name))
			instances.append(instance_health['InstanceId'])

	return instances


def adjust_capacity(client, asg_name, desired_size, max_size):
	print("Adjusting desired capacity to %s on %s" % (desired_size, asg_name))
	if max_size < desired_size:
		max_size = desired_size
		print("Adjusting max size to %s" % (max_size))
	
	if query_yes_no("Do you want to adjust the capacity of the ASG?"):
		response = client.update_auto_scaling_group(
		    AutoScalingGroupName=asg_name,
		    MaxSize=max_size,
		    DesiredCapacity=desired_size
		)
	time.sleep(3)
	print_new_state()


def drain_instance_from_elb(client, elb_name, instance_id):
	print("Draining down %s from ELB %s" % (instance_id, elb_name))

	if query_yes_no("Do you want to drain the instance from the ELB?"):
		response = client.deregister_instances_from_load_balancer(
		    LoadBalancerName=elb_name,
		    Instances=[
		        {
		            'InstanceId': instance_id
		        },
		    ]
		)

	in_service = list(get_instances_in_service_from_elb(client, elb_name))
	while instance_id in in_service:
		print("Instance %s still in service. Sleeping 5 seconds." % (instance_id))
		time.sleep(5)
		in_service = list(get_instances_in_service_from_elb(client, elb_name))

	print_new_state()


def terminate_instance_from_asg(client, asg_name, instance_id, decrement_capacity=False):
	print("Terminating %s from ASG %s" % (instance_id, asg_name))
	
	if query_yes_no("Do you want to terminate the instance?"):
		response = client.terminate_instance_in_auto_scaling_group(
		    InstanceId=instance_id,
		    ShouldDecrementDesiredCapacity=decrement_capacity
		)
	time.sleep(3)
	print_new_state()


def wait_for_instance_inservice(client, elb_name, instance_id, desired_size):
	in_service = []
	while len(in_service) != desired_size:
		in_service = list(get_instances_in_service_from_elb(client, elb_name))
		print("Found %s instances: %s. Expected capacity: %s. Sleeping 10 seconds." % (len(in_service), in_service, desired_size))
		if instance_id is not None and instance_id in in_service:
			in_service.remove(instance_id)
		time.sleep(10)

	print("Found %s instances: %s. Moving ahead!" % (len(in_service), in_service))
	print_new_state()


def main(argv):
    region = 'us-east-1'
    adjusted_capacity = 0
    global client_elb, client, elb_name, asg_name, assume_yes
    
    try:
      opts, args = getopt.getopt(argv, "r:a:y")

      for opt, arg in opts:
          if opt in('-r'):
            if arg == 'tokyo':
              region = 'ap-northeast-1'
            elif arg == 'mumbai':
              region = 'ap-douth-1'
            elif arg == 'us-east':
              region = 'us-east-1'
            elif arg == 'dublin':
              region = 'eu-west-1'
            elif arg == 'singapore':
              region = 'ap-southeast-1'          
          if opt in ('-a'):          
            asg_name = arg
          if opt in ('-y'):
		  	assume_yes = True
    except getopt.GetoptError, err:
      print >>sys.stderr, err
      sys.exit(2)

    print("Region: " + region)

    if asg_name is None:
    	exit("Missing ASG name. Use -a to specify the ASG. Exiting.")

    client = boto3.client('autoscaling', region_name=region)
    client_elb = boto3.client('elb', region_name=region)

    # get autoscaling group
    elb_name, desired_size, max_size = get_elb_from_asg_info(client, asg_name)

    print_new_state()

    asg_instances = get_instances_from_asg(client, asg_name)
    elb_instances = get_instances_in_service_from_elb(client_elb, elb_name)
    
    if len(asg_instances) != len(elb_instances):
    	if (set(asg_instances) & set(elb_instances)) == (set(elb_instances) & set(asg_instances)):
    		exit("ASG and ELB must handle the same instances")

    if desired_size == 1:
    	single_instance_id = elb_instances[0]
    	adjust_capacity(client, asg_name, desired_size+1, max_size)
    	wait_for_instance_inservice(client_elb, elb_name, None, desired_size+1)
    	drain_instance_from_elb(client_elb, elb_name, single_instance_id)
    	print("Waiting 40 seconds before terminating the instance %s" % (single_instance_id))
    	time.sleep(40)
    	terminate_instance_from_asg(client, asg_name, single_instance_id, decrement_capacity=True)
    	adjust_capacity(client, asg_name, desired_size, max_size) # re-adjust the max-size
    else:
	    for instance in elb_instances:
	    	drain_instance_from_elb(client_elb, elb_name, instance)
	    	print("Waiting 40 seconds before terminating the instance %s" % (instance))
	    	time.sleep(40)
	    	terminate_instance_from_asg(client, asg_name, instance)
	    	wait_for_instance_inservice(client_elb, elb_name, instance, desired_size)

    print("Completed!")

if __name__ == "__main__":
    main(sys.argv[1:])

