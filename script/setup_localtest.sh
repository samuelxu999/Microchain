#!/bin/bash

## variable
localtest_folder="../local_test"
src_folder="../src"
config_folder="../config"

## new folder based on test node size
for i in 1 2 3 4 5
do
	# new folders for local test
	if [ ! -d "$localtest_folder$i" ]
	then
		mkdir $localtest_folder$i
	fi

	## copy server and client code to localtest folder
	cp $src_folder/WS_Server.py $localtest_folder$i/
	cp $src_folder/WS_Client.py $localtest_folder$i/

	## copy libs to localtest folder
	cp -r $src_folder/cryptolib $localtest_folder$i/
	cp -r $src_folder/network $localtest_folder$i/
	cp -r $src_folder/consensus $localtest_folder$i/
	cp -r $src_folder/randomness $localtest_folder$i/
	cp -r $src_folder/utils $localtest_folder$i/
	cp -r $src_folder/kademlia $localtest_folder$i/
	cp -r $src_folder/rpcudp $localtest_folder$i/

	## copy data
	# cp -r $src_folder/data $localtest_folder$i/

	## copy swarm_server.json
	# cp $config_folder/swarm_server.json $localtest_folder$i/

	## clear test data and results
	rm -rf $localtest_folder$i/chaindata/*
	rm -rf $localtest_folder$i/randomdata/*
	rm -rf $localtest_folder$i/test_results/*
	rm -rf $localtest_folder$i/nodedata/*

done

# ## clear test data and results
# rm -rf ./chaindata/*
# rm -rf ./randomdata/*
# rm -rf ./test_results/*
# rm -f ./nodedata/*
# touch ./WS_Server.py
