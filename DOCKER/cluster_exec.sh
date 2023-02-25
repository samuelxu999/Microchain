#!/bin/bash

## ============= Run cluster by launching multiple containerized geth nodes given args ==============
OPERATION=$1

## Start cluster
if  [ "start" == "$OPERATION" ] ; then
	echo "Start a bootstrap node"
	sudo ./service_run.sh start microchain_bootstrap x86 30180 8080
	sleep 5

	echo "Start four validators"
	sudo ./service_run.sh start microchain_node1 x86 30181 8081 0.0.0.0:30180
	sudo ./service_run.sh start microchain_node2 x86 30182 8082 0.0.0.0:30180
	sudo ./service_run.sh start microchain_node3 x86 30183 8083 0.0.0.0:30180
	sudo ./service_run.sh start microchain_node4 x86 30184 8084 0.0.0.0:30180

## Stop cluster
elif [ "stop" == "$OPERATION" ] ; then
	echo "Stop cluster"
	sudo ./service_run.sh stop microchain_bootstrap
	sudo ./service_run.sh stop microchain_node1
	sudo ./service_run.sh stop microchain_node2
	sudo ./service_run.sh stop microchain_node3
	sudo ./service_run.sh stop microchain_node4

## show cluster
elif [ "show" == "$OPERATION" ] ; then
	echo "Show cluster"
	sudo ./service_run.sh show

## Show usage
else
	echo "Usage $0 -operation(start|stop|show)"
fi