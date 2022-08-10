#!/usr/bin/env python

'''
========================
Test_Client module
========================
Created on August.10, 2022
@author: Xu Ronghua
@Email:  rxu22@binghamton.edu
@TaskDescription: This module provide client App that execute test cases for demo.
'''
import argparse
import sys
import time
import logging
import asyncio

from utils.utilities import TypesUtil, FileUtil
from utils.Client_RPC import Client_RPC

logger = logging.getLogger(__name__)

## ======== verify checkpoint at the end of epoch by voting process ===================
def query_checkpoint_netInfo(isDisplay=False):
	## get validators information in net.
	validator_info = Client_instace.query_validators()

	fininalized_count = {}
	justifized_count = {}
	processed_count = {}

	## -------------  Calculate all checkpoints count -------------------
	for validator in validator_info:
		# Calculate finalized checkpoint count
		if validator['highest_finalized_checkpoint'] not in fininalized_count:
			fininalized_count[validator['highest_finalized_checkpoint']] = 0
		fininalized_count[validator['highest_finalized_checkpoint']] += 1
		
		# Calculate justified checkpoint count
		if validator['highest_justified_checkpoint'] not in justifized_count:
			justifized_count[validator['highest_justified_checkpoint']] = 0
		justifized_count[validator['highest_justified_checkpoint']] += 1

		# Calculate processed checkpoint count
		if validator['processed_head'] not in processed_count:
			processed_count[validator['processed_head']] = 0
		processed_count[validator['processed_head']] += 1

	if(isDisplay):
		logger.info("")
		logger.info("Finalized checkpoints: {}\n".format(fininalized_count))
		logger.info("Justified checkpoints: {}\n".format(justifized_count))
		logger.info("Processed checkpoints: {}\n".format(processed_count))

	## -------------- search finalized checkpoint with maximum count -------------
	checkpoint = ''
	max_acount = 0
	for _item, _value in fininalized_count.items():
		if(_value > max_acount):
			max_acount = _value
			checkpoint = _item	
	finalized_checkpoint = [checkpoint, max_acount]
	if(isDisplay):
		logger.info("Finalized checkpoint: {}    count: {}\n".format(finalized_checkpoint[0],
															   finalized_checkpoint[1]))

	## --------------- search finalized checkpoint with maximum count -------------
	checkpoint = ''
	max_acount = 0
	for _item, _value in justifized_count.items():
		if(_value > max_acount):
			max_acount = _value
			checkpoint = _item	
	justified_checkpoint = [checkpoint, max_acount]
	if(isDisplay):
		logger.info("Justified checkpoint: {}    count: {}\n".format(justified_checkpoint[0],
															   justified_checkpoint[1]))

	## -----------------search finalized checkpoint with maximum count -------------
	checkpoint = ''
	max_acount = 0
	for _item, _value in processed_count.items():
		if(_value > max_acount):
			max_acount = _value
			checkpoint = _item	
	processed_checkpoint = [checkpoint, max_acount]
	if(isDisplay):
		logger.info("Processed checkpoint: {}    count: {}\n".format(processed_checkpoint[0],
															   processed_checkpoint[1]))

	## build json date for return.
	json_checkpoints={}
	json_checkpoints['finalized_checkpoint'] = finalized_checkpoint
	json_checkpoints['justified_checkpoint'] = justified_checkpoint
	json_checkpoints['processed_checkpoint'] = processed_checkpoint

	return json_checkpoints

def define_and_get_arguments(args=sys.argv[1:]):
	parser = argparse.ArgumentParser(description="Run websocket client.")
	
	parser.add_argument("--test_func", type=int, default=2, help="test function: \
															0: infromation query \
															1: validator test \
															2: single step test \
															3: randshare test")
	parser.add_argument("--op_status", type=int, default=0, help="operational function mode")
	parser.add_argument("--tx_size", type=int, default=128, help="Size of value in transaction.")
	parser.add_argument("--tx_thread", type=int, default=10, help="Transaction-threads count.")
	parser.add_argument("--test_round", type=int, default=1, help="test evaluation round")
	parser.add_argument("--wait_interval", type=int, default=1, help="break time between step.")
	parser.add_argument("--bootstrapnode", default='0.0.0.0:8081', type=str, 
						help="bootstrap node address format[ip:port] to join the network.")
	parser.add_argument("--target_address", type=str, default="0.0.0.0:8080", 
						help="Test target address - ip:port.")
	parser.add_argument("--data", type=str, default="", 
						help="Input date for test.")
	args = parser.parse_args(args=args)
	return args

if __name__ == "__main__":
	FORMAT = "%(asctime)s %(levelname)s | %(message)s"
	LOG_LEVEL = logging.INFO
	logging.basicConfig(format=FORMAT, level=LOG_LEVEL)

	Client_RPC_logger = logging.getLogger("Client_RPC")
	Client_RPC_logger.setLevel(logging.INFO)

	# get arguments
	args = define_and_get_arguments()

	# set parameters
	bootstrap_address = args.bootstrapnode
	target_address = args.target_address
	tx_thread = args.tx_thread
	tx_size = args.tx_size
	test_func = args.test_func
	op_status = args.op_status
	wait_interval = args.wait_interval
	test_run = args.test_round

	# ------------------------ Instantiate the ENFchain_RPC ----------------------------------
	Client_instace = Client_RPC(bootstrap_address)

	## ------------------------ test cases ---------------------------------
	if(test_func == 0):
		if(op_status == 1):
			neighbors = Client_instace.query_neighbors(target_address)['neighbors']
			for node in neighbors:
				logger.info(node)
		elif(op_status == 2):
			account_info = Client_instace.query_account(target_address)
			logger.info(account_info)
		elif(op_status == 3):
			validator_info = Client_instace.query_validator(target_address)
			logger.info(validator_info)
		elif(op_status == 4):
			tx_pool = Client_instace.query_tx_pool(target_address)
			logger.info(tx_pool)
		elif(op_status == 5):
			tx_hash = args.data
			list_tx = Client_instace.query_tx(target_address, tx_hash)
			for tx in list_tx:
				count_tx_size=len( tx[2].encode('utf-8'))
				logger.info("{}, committed in block:{}, size:{}.\n".format(TypesUtil.string_to_json(tx[2]),
																tx[3], count_tx_size))
		elif(op_status == 6):
			block_hash = args.data
			json_block = Client_instace.query_blk(target_address, block_hash)
			if(json_block!={}):
				block_size = len( TypesUtil.json_to_string(json_block).encode('utf-8'))
				tx_count = len(json_block['transactions'])
				logger.info("{}, size:{}, tx_count:{}".format(json_block, 
														block_size, tx_count))
		elif(op_status == 7):
			ledger_data = Client_instace.query_ledger(target_address)
			for blk in ledger_data['chain']:
				logger.info(blk)
			logger.info('Length: {}'.format(ledger_data['length']))
		else:
			# display nodes
			for node in Client_instace.nodes:
				logger.info(node)

	elif(test_func == 1):
		pass
	elif(test_func == 2):
		if(op_status == 10):
			## build a dummy json_tx for test.
			json_tx={}
			json_tx['name']='Samuel'
			json_tx['age']=28
			ret_msg = Client_instace.submit_tx(target_address, json_tx)
			logger.info(ret_msg)
		elif(op_status == 11):
			## throughput test based on tps, random distributed among nodes
			Client_instace.submit_txs(tx_thread, tx_size)
		elif(op_status == 2):
			Client_instace.exec_mining()
		elif(op_status == 3):
			Client_instace.exec_check_head()
		elif(op_status == 4):
			Client_instace.exec_voting()
		else:
			# get checkpoint after execution
			json_checkpoints = query_checkpoint_netInfo(False)
			for _item, _value in json_checkpoints.items():
				logger.info("{}: {}    {}".format(_item, _value[0], _value[1]))
	else:
		logger.info("Unknown test_func.")