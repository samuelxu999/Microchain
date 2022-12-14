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
import os
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

def query_validator_status():
	## get validators status in net.
	validators_status = Client_instace.query_validators_status()
	
	for status_data in validators_status:
		# if(node_status['consensus_status']!=4):
		# 	unconditional_nodes.append(node)
		logger.info("address:{}    consensus_run: {}     consensus_status: {}".format(status_data['address'], 
					status_data['consensus_run'], status_data['consensus_status']))

	# logger.info("Non-syn node: {}".format(unconditional_nodes))

# ====================================== validator test ==================================
def Epoch_Test(target_address, op_status, tx_size, tx_count, phase_delay):
	'''
	This test network latency for one epoch life time:
	'''
	## Define ls_time_exec to save executing time to log
	ls_time_exec=[]

	## S1: send test transactions
	start_time=time.time()
	# for tps_round in range(tx_count):
	if(op_status==1):
		## build a dummy json_tx for test.
		json_tx={}
		json_tx['name']='Samuel'
		json_tx['age']=28
		ret_msg = Client_instace.submit_tx(target_address, json_tx)
		logger.info(ret_msg)
	else:
		Client_instace.submit_txs(tx_count, tx_size)
	exec_time=time.time()-start_time
	ls_time_exec.append(format(exec_time*1000, '.3f'))

	time.sleep(phase_delay)

	## S2: start mining 
	start_time=time.time()   
	Client_instace.exec_mining()
	exec_time=time.time()-start_time
	ls_time_exec.append(format(exec_time*1000, '.3f'))

	time.sleep(phase_delay)

	## S3: fix head of epoch 
	start_time=time.time()   
	Client_instace.exec_check_head()
	exec_time=time.time()-start_time
	ls_time_exec.append(format(exec_time*1000, '.3f'))

	time.sleep(phase_delay)

	## S4: voting block to finalize chain
	start_time=time.time() 
	Client_instace.exec_voting()
	exec_time=time.time()-start_time
	ls_time_exec.append(format(exec_time*1000, '.3f'))

	time.sleep(phase_delay)

	logger.info("txs: {}    mining: {}    fix_head: {}    vote: {}\n".format(ls_time_exec[0],
										ls_time_exec[1], ls_time_exec[2], ls_time_exec[3]))
	## Prepare log messgae
	str_time_exec=" ".join(ls_time_exec)
	## Save to *.log file
	FileUtil.save_testlog('test_results', 'exec_time.log', str_time_exec)

def show_tx_size(target_address):
	json_response = Client_instace.query_ledger(target_address)
	chain_data = json_response['chain']
	chain_length = json_response['length']
	logger.info('Chain length: {}'.format(chain_length))
	## get the latest unempty block
	for block in reversed(chain_data):
		if(block['transactions']!=[]): 
			blk_str = TypesUtil.json_to_string(block)  
			logger.info('Block size: {} Bytes'.format(len( blk_str.encode('utf-8') ))) 
			logger.info('transactions count: {}'.format(len( block['transactions'] )))  

			tx=block['transactions'][0]
			tx_str=TypesUtil.json_to_string(tx)
			logger.info('Tx size: {} Bytes'.format(len( tx_str.encode('utf-8') )))
			break

## evaluation on how long to submit tx and commit it on ledger.
def submit_tx_evaluate(target_address, tx_size):
	tx_time = 0.0

	## using random byte string for value of tx; value can be any bytes string.
	json_tx={}
	json_tx['data']=TypesUtil.string_to_hex(os.urandom(tx_size)) 

	## submit tx and get tx_hash
	tx_hash = Client_instace.submit_tx(target_address, json_tx)['submit_transaction']
	commit_block =''

	time.sleep(1)

	logger.info("wait until tx:{} is committed...\n".format(tx_hash))
	start_time=time.time()
	while(True):
		list_tx = Client_instace.query_tx(target_address, tx_hash)

		if(list_tx[0][3]!='0'):
			commit_block = list_tx[0][3]
			break

		time.sleep(0.5)
		tx_time +=0.5
		if(tx_time>=30):
			logger.info("Timeout, tx commit fail.") 
			break

	exec_time=time.time()-start_time
	logger.info("tx is committed in block {}, time: {:.3f}\n".format(commit_block, exec_time, '.3f')) 
	FileUtil.save_testlog('test_results', 'exec_tx_commit.log', format(exec_time, '.3f'))

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
		elif(op_status == 8):
			show_tx_size(target_address)
		else:
			# display nodes
			for node in Client_instace.nodes:
				logger.info(node)

	elif(test_func == 1):
		for x in range(test_run):
			logger.info("Test run:{}".format(x+1))
			if(op_status==2):
				submit_tx_evaluate(target_address, tx_size)
			else:
				Epoch_Test(target_address, op_status, tx_size, tx_thread, wait_interval)
		
		## display checkpoint status.
		json_checkpoints = query_checkpoint_netInfo(False)
		for _item, _value in json_checkpoints.items():
			logger.info("{}: {}    {}".format(_item, _value[0], _value[1]))
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
		elif(op_status == 12):
			submit_tx_evaluate(target_address, tx_size)
		elif(op_status == 2):
			Client_instace.exec_mining()
		elif(op_status == 3):
			Client_instace.exec_check_head()
		elif(op_status == 4):
			Client_instace.exec_voting()
		elif(op_status == 9):
			Client_instace.start_consensus()
		elif(op_status == 90):
			query_validator_status()
		else:
			json_checkpoints = query_checkpoint_netInfo(False)
			for _item, _value in json_checkpoints.items():
				logger.info("{}: {}    {}".format(_item, _value[0], _value[1]))
	else:
		logger.info("Unknown test_func.")