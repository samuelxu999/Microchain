'''
========================
validator.py
========================
Created on May.31, 2019
@author: Xu Ronghua
@Email:  rxu22@binghamton.edu
@TaskDescription: This module provide blockchain implementation.
@Reference: 
'''

from collections import OrderedDict
import os
import binascii
import threading
import logging
import time
import asyncio
import json
import time
from urllib.parse import urlparse
from uuid import uuid4
import copy

from utils.utilities import FileUtil, TypesUtil, FuncUtil
from network.wallet import Wallet
from consensus.transaction import Transaction
from network.nodes import Nodes
from consensus.block import Block
from consensus.vote import VoteCheckPoint
from utils.db_adapter import DataManager
from consensus.consensus import *
from utils.configuration import *
from utils.service_api import SrvAPI
from utils.Microchain_RPC import Microchain_RPC

logger = logging.getLogger(__name__)

class Validator():
	'''
	--------------------------- A Validator contains the following arguments: ----------------------------------
	self.node_id: 						GUID 
	self.consensus: 					Consensus algorithm
	self.chain_db: 						local chain database adapter
	self.consensus: 					consensus algorithm
	self.wallet: 						wallet account management
	self.peer_nodes: 					peer nodes management 
	self.verify_nodes: 					verify nodes management 

	self.transactions: 					local transaction pool
	self.chain: 						local chain data buffer
	self.block_dependencies: 			used to save blocks need for dependency
	self.vote_dependencies: 			used to save pending vote need for dependency
	self.processed_head: 				the latest processed descendant of the highest justified checkpoint
	self.current_head: 					the current received descendant of the highest justified checkpoint
	self.highest_justified_checkpoint: 	the block with higest justified checkpoint
	self.highest_finalized_checkpoint: 	the block with higest finalized checkpoint
	
	self.votes: 						Map {sender -> vote_db object} which contains all the votes data for check
	self.vote_count: 					Map {source_hash -> {target_hash -> count}} to count the votes

	self.sum_stake:						Summary of stake that all validators, used for PoS;
	self.committee_size:				Number of validators to participant the consensus committee;
	self.block_epoch:					Block proposal epoch size, used for set finalized checkpoint;
	
	self.msg_buf: 						Buffer messages which are procossed by daemon function process_msg(self)
	self.rev_thread: 					daemon thread object to handle process_msg(self)
	--------------------------------------------------------------------------------------------------------------
	''' 

	def __init__(self, 	port, bootstrapnode,
						consensus=ConsensusType.PoW, 
						block_epoch=EPOCH_SIZE, 
						pause_epoch=1, 
						phase_delay=BOUNDED_TIME,
						frequency_peers=600):

		# Instantiate the Wallet
		self.wallet = Wallet()
		self.wallet.load_accounts()

		# Instantiate the PeerNodes
		self.peer_nodes = Nodes(db_file = PEERS_DATABASE)
		self.peer_nodes.load_ByAddress()

		# Instantiate the verified Nodes
		self.verify_nodes = Nodes(db_file = VERIFY_DATABASE)

		# New database manager to manage chain data
		self.chain_db = DataManager(CHAIN_DATA_DIR, BLOCKCHAIN_DATA)
		self.chain_db.create_table(CHAIN_TABLE)

		## New database manager to manage tx data
		self.tx_db = DataManager(CHAIN_DATA_DIR, TX_DATA)
		self.tx_db.create_tx_table(TX_TABLE)

		## Create genesis block
		genesis_block = Block()
		json_data = genesis_block.to_json()

		## no local chain data, generate a new validator information
		if( self.chain_db.select_block(CHAIN_TABLE)==[] ):
			#add genesis_block as 2-finalized
			self.add_block(json_data, 2)
		
		## new chain buffer
		self.chain = []

		## new transaction pool
		self.transactions = []                            

		## votes pool Map {sender -> vote_db object}
		self.votes = {}

		## choose consensus algorithm
		self.consensus = consensus

		## -------------- load chain info ---------------
		chain_info = self.load_chainInfo()
		if(chain_info == None):
			#Generate random number to be used as node_id
			self.node_id = str(uuid4()).replace('-', '')

			## initialize pending data buffer
			self.block_dependencies = {}
			self.vote_dependencies = {}
			self.processed_head = json_data
			self.highest_justified_checkpoint = json_data
			self.highest_finalized_checkpoint = json_data
			#self.votes = {}
			self.vote_count = {}
			## update chain info
			self.save_chainInfo()
		else:
			#Generate random number to be used as node_id
			self.node_id = chain_info['node_id']
			self.block_dependencies = chain_info['block_dependencies']
			self.vote_dependencies = chain_info['vote_dependencies']
			self.processed_head = chain_info['processed_head']
			self.highest_justified_checkpoint = chain_info['highest_justified_checkpoint']
			self.highest_finalized_checkpoint = chain_info['highest_finalized_checkpoint']
			#self.votes = chain_info['votes']
			self.vote_count = chain_info['vote_count']
		
		## point current head to processed_head
		self.current_head = self.processed_head

		## set total stake and number of validators
		ls_nodes=list(self.peer_nodes.get_nodelist())
		## set sum_stake is peer nodes count
		self.sum_stake = len(ls_nodes)
		## set committee_size as peer nodes count 
		self.committee_size = len(ls_nodes)
		## set block_epoch given args
		self.block_epoch = block_epoch;

		''' 
		Threading as daemon to process received message.
		The process_msg() method will be started and it will run in the background
		until the application exits.
		'''
		## new buffer list to process received message by on_receive().
		self.msg_buf = []
		## define a thread to handle received messages by executing process_msg()
		self.rev_thread = threading.Thread(target=self.process_msg, args=())
		## Set as daemon thread
		self.rev_thread.daemon = True
		## Start the daemonized method execution
		self.rev_thread.start()   

		''' 
		Threading as daemon to process consensus protocol.
		The exec_consensus() method will be started and it will run in the background
		until the application exits.
		'''
		## the flag used to trigger consensus protocol execution.
		self.runConsensus = False
		## set pause threshold for check synchronization
		self.pause_epoch = pause_epoch
		## set delay time between operations in consensus protocol.
		self.phase_delay = phase_delay
		## define a thread to handle received messages by executing process_msg()
		self.consensus_thread = threading.Thread(target=self.exec_consensus, args=())
		## Set as daemon thread
		self.consensus_thread.daemon = True
		## Start the daemonized method execution
		self.consensus_thread.start()
		## Indicate current consensus status: 
		## 0-ENF proposal; 1-ENF-mining; 2-fix head; 
		## 3-voting-based finality; 4-synchronization
		self.statusConsensus = 0 

		## ------------------------ Instantiate the Microchain_RPC ----------------------------------
		self.RPC_client = Microchain_RPC(keystore="keystore", 
											keystore_net="keystore_net")   
		self.frequency_peers = frequency_peers
		self.bootstrapnode = bootstrapnode
		self.port = port
		## define a thread to handle refresh_peers()
		self.peers_thread = threading.Thread(target=self.refresh_peers, args=())
		## Set as daemon thread
		self.peers_thread.daemon = True
		## Start the daemonized method execution
		self.peers_thread.start()

	## =================================== daemon function ================================
	def refresh_peers(self):
		'''
		daemon thread function: handle message and save into local database
		'''
		# this variable is used as waiting time when there is no message for process.
		while(True):
			time.sleep(self.frequency_peers)
			logger.info("Refresh alive peers' information")
			try:
				bootstrapnode_address = self.bootstrapnode.split(':')[0]+":80"+ self.bootstrapnode.split(':')[1][3:] 
				host_address = "0.0.0.0:"+str(self.port)

				## Prerequisite: query p2p peers information
				tasks = [self.RPC_client.get_peers_info(host_address)]
				loop = asyncio.new_event_loop()
				done, pending = loop.run_until_complete(asyncio.wait(tasks))
				peers_info = []
				for future in done:
					peers_info = future.result()
				loop.close()

				## 1) for each json_peer to add peers
				ls_peer = []
				for json_peer in peers_info:
					## Do not add bootstrapnode into consensus node list
					# logger.info('node_url: {}    bootstrapnode:{}'.format(json_peer['node_url'],bootstrapnode_address))
					if(json_peer['node_url']==bootstrapnode_address):
						logger.info('Not add bootstrapnode into consensus node list.')
					else:
						# logger.info(json_peer['address'])
						self.peer_nodes.register_node(json_peer['address'], 
														json_peer['public_key'], 
														json_peer['node_url'])
						ls_peer.append(json_peer['address'])

				## reload peer node
				self.peer_nodes.load_ByAddress()

				## 2) Add host node into consensus node list and ls_peer
				if(self.wallet.accounts!=0):
					json_host = {}
					host_account = self.wallet.accounts[0]
					json_host['address'] = host_account['address']
					json_host['public_key'] = host_account['public_key']
					json_host['node_url'] = host_address

					## send host node information to bootstrapnode to keep alive.
					self.RPC_client.add_verifynode(bootstrapnode_address, json_host)

					ls_nodes = []
					peer_nodes = copy.deepcopy(self.peer_nodes.nodes)
					for node in peer_nodes:
						ls_nodes.append(node[1])

					# logger.info('host_address: {}    ls_nodes:{}'.format(json_host['address'], ls_nodes))
					if(json_host['address'] not in ls_nodes):
						logger.info('Add host node into consensus node list.')
						self.peer_nodes.register_node(json_host['address'], 
														json_host['public_key'], 
														json_host['node_url'])

						## reload peer node
						self.peer_nodes.load_ByAddress()

					## put host node into ls_peer
					ls_peer.append(json_host['address'])

				ls_nodes = []
				peer_nodes = copy.deepcopy(self.peer_nodes.nodes)
				for node in peer_nodes:
					ls_nodes.append(node[1])

				## 3) remove inactive peers from consensus node list
				for node in ls_nodes: 
					if(node not in ls_peer):
						logger.info('Remove {} from consensus node list.'.format(node))
						self.peer_nodes.remove_peernode(node)
				## reload peer node
				self.peer_nodes.load_ByAddress()

				## set total stake and number of validators
				ls_nodes=list(self.peer_nodes.get_nodelist())
				self.sum_stake = len(ls_nodes) 
				self.committee_size = len(ls_nodes)
			except:
				logger.info('\n! Some error happen in peers_thread.\n')
			finally:
				pass


	def process_msg(self):
		'''
		daemon thread function: handle message and save into local database
		'''
		# this variable is used as waiting time when there is no message for process.
		idle_time=0.0
		while(True):
			# ========= idle time incremental strategy, the maximum is 1 seconds ========
			if( len(self.msg_buf)==0 ):
				idle_time+=0.1
				if(idle_time>1.0):
					idle_time=1.0
				time.sleep(idle_time)
				continue
			
			# reset idle time as 0
			idle_time = 0.0

			try:
				# ============= Choose a message from buffer and process it ==================
				msg_data = self.msg_buf[0]
				if(msg_data[0]==1):
					self.add_block(msg_data[1], msg_data[2])			
				elif(msg_data[0]==2):
					VoteCheckPoint.add_voter_data(msg_data[1], msg_data[2])
				elif(msg_data[0]==3):
					self.commit_tx(msg_data[1], msg_data[2])
				else:
					self.add_tx(msg_data[1])
				
				self.msg_buf.remove(msg_data)
			except:
				logger.info('\n! Some error happen in process_msg.\n')
			finally:
				pass

	def exec_consensus(self):
		'''
		daemon thread function: execute consensus protocol
		'''
		# used as waiting time as pending consensus protocol execution.
		idle_time=0.0
		# Used to synchronization after certain epoch height.
		pause_epoch=0
		while(True):
			# ========= idle time incremental strategy, the maximum is 1 seconds ========
			if(not self.runConsensus):
				idle_time+=0.1
				if(idle_time>1.0):
					idle_time=1.0
				time.sleep(idle_time)
				pause_epoch=0
				continue

			try:
				# reset idle time as 0
				idle_time = 0.0

				# ========================== Run consensus protocol ==========================
				json_head=self.processed_head
				logger.info("Consensus run at height: {}    status: {}".format(json_head['height'], 
																			self.runConsensus))
				## ------------S1: execute proof-of-work to mine new block--------------------
				start_time=time.time()
				new_block=self.mine_block()
				exec_time=time.time()-start_time
				FileUtil.save_testlog('test_results', 'exec_mining.log', format(exec_time*1000, '.3f'))
				
				## broadcast proposed block to peer nodes
				if( (self.consensus==ConsensusType.PoW) or 
					(not Block.isEmptyBlock(new_block)) ):
					SrvAPI.broadcast_POST(self.peer_nodes.get_nodelist(), new_block, '/test/block/verify')
				time.sleep(self.phase_delay*1.5)

				## ------------S2: fix head of current block generation epoch ----------------
				self.fix_processed_head()
				time.sleep(self.phase_delay)

				## ------------S3: voting block to finalize chain ----------------------------
				json_head= self.processed_head

				## only vote if current height arrive multiple of EPOCH_SIZE
				if( (json_head['height'] % self.block_epoch) == 0):
					vote_data = self.vote_checkpoint(json_head)	
					SrvAPI.broadcast_POST(self.peer_nodes.get_nodelist(), vote_data, '/test/vote/verify')
					pause_epoch+=1
					time.sleep(self.phase_delay*3)
			
				## if pause_epoch arrives threshold. stop consensus for synchronization
				if(pause_epoch==self.pause_epoch):
					self.runConsensus=False
					logger.info("Consensus run status: {}".format(self.runConsensus))

			except:
				logger.info('\n! Some error happen in exec_consensus.\n')
			finally:
				pass


	def print_config(self):
		'''
		Show validator configuration and information
		'''		
		accounts = self.wallet.list_address()
		logger.info("Current accounts: {}".format(len(accounts)))
		if accounts:
			i=0
			for account in accounts:
			    logger.info("[{}]: {}".format(i, account) )
			    i+=1

		nodes = self.peer_nodes.get_nodelist()
		logger.info("Peer nodes: {}".format(len(nodes)))
		for node in nodes:
			json_node = TypesUtil.string_to_json(node)
			logger.info('    {}    {}'.format(json_node['address'], json_node['node_url']) )

		# Instantiate the Blockchain
		logger.info("Chain information:")
		logger.info("    uuid:                         {}".format(self.node_id))
		logger.info("    main chain blocks:            {}".format(self.processed_head['height']+1))
		logger.info("    consensus:                    {}".format( self.consensus.name) )
		logger.info("    block proposal epoch:         {}".format( self.block_epoch) )
		logger.info("    pause epoch size:             {}".format( self.pause_epoch) )
		logger.info("    current head:                 {}    height: {}".format(self.current_head['hash'],
																				self.current_head['height']))
		logger.info("    processed head:               {}    height: {}".format(self.processed_head['hash'],
																				self.processed_head['height']))
		logger.info("    highest justified checkpoint: {}    height: {}".format(self.highest_justified_checkpoint['hash'],
																				self.highest_justified_checkpoint['height']) )
		logger.info("    highest finalized checkpoint: {}    height: {}".format(self.highest_finalized_checkpoint['hash'],
																				self.highest_finalized_checkpoint['height']) )


	## =================================== tx operation ===================================
	def add_tx(self, json_tx):
		'''
		Database operation: add verified tx to local ledger database
		'''
		# if tx not existed, add tx to database
		if( self.tx_db.select_tx(TX_TABLE, json_tx['hash'])==[] ):
			self.tx_db.insert_tx(TX_TABLE,	json_tx['hash'], 
								TypesUtil.json_to_string(json_tx))

	def commit_tx(self, tx_hash, block_hash):
		'''
		Database operation: update block_hash to fix tx on local tx database.
		'''
		self.tx_db.update_tx(TX_TABLE, tx_hash, block_hash)

	def query_tx(self, tx_hash,  tx_num=10):
		'''
		Query operation: select a tx as json given tx_hash
		'''
		ret_tx = []

		list_tx = self.tx_db.select_tx(TX_TABLE, tx_hash)
		txs_size = len(list_tx)
		if(txs_size<tx_num):
			ret_tx = list_tx
		else:
			ret_tx = list_tx[txs_size-tx_num:]

		return ret_tx

	## =================================== block operation =====================================
	def add_block(self, json_block, status=0):
		'''
		Database operation: add verified block to local chain data
		'''
		# if block not existed, add block to database
		if( self.chain_db.select_block(CHAIN_TABLE, json_block['hash'])==[] ):
			self.chain_db.insert_block(CHAIN_TABLE,	json_block['hash'], 
								TypesUtil.json_to_string(json_block), status)

	def update_blockStatus(self, block_hash, status):
		'''
		Database operation: update block status
		'''
		self.chain_db.update_status(CHAIN_TABLE, block_hash, status)

	def get_block(self, block_hash):
		'''
		Database operation: select a block as json given block_hash
		'''
		ls_block = self.chain_db.select_block(CHAIN_TABLE, block_hash)
		if(len(ls_block)!=0):
			str_block = ls_block[-1][2]
			return TypesUtil.string_to_json(str_block)
		else:
			return {}

	def query_block(self, block_hash):
		'''
		Query operation: select a block with status as json given block_hash
		'''
		ls_block = self.chain_db.select_block(CHAIN_TABLE, block_hash)
		if(len(ls_block)!=0):
			json_block = TypesUtil.string_to_json(ls_block[-1][2])
			json_block['status'] = ls_block[-1][3]
			return json_block
		else:
			return {}

	## =================================== node operation ===================================
	def get_node(self, node_address):
		'''
		Check node: select a node from node buffers given node address
		'''

		## 1) search target node in peer nodes
		ls_peernodes=list(self.peer_nodes.get_nodelist())

		# refresh sum_stake and committee_size as peer nodes change
		# set sum_stake is peer nodes count
		self.sum_stake = len(ls_peernodes)
		# set committee size as peer nodes count 
		self.committee_size = len(ls_peernodes)

		json_node = None

		for node in ls_peernodes:
			tmp_node = TypesUtil.string_to_json(node)
			if(tmp_node['address']==node_address):
				json_node = tmp_node
				break	
		## return found node
		if(json_node != None):			
			return json_node

		## 2) search target node in verify nodes
		self.verify_nodes.load_ByAddress(node_address)
		ls_verifynodes=list(self.verify_nodes.get_nodelist())

		for node in ls_verifynodes:
			tmp_node = TypesUtil.string_to_json(node)
			if(tmp_node['address']==node_address):
				json_node = tmp_node
				break	
		## return found node
		if(json_node != None):			
			return json_node

		## 3) query node from bootstrap server
		bootstrapnode_address = self.bootstrapnode.split(':')[0]+":80"+ self.bootstrapnode.split(':')[1][3:] 
		json_node=self.RPC_client.check_verifynode(bootstrapnode_address, node_address)['node']

		if(json_node!='{}'):
			## add node to local verifynode.
			self.verify_nodes.register_node(json_node['address'], json_node['public_key'], json_node['node_url'])

		return json_node


	def valid_round(self, node_address):
		'''
		Verify round operation: check if a node is valid given current block height
		'''
		if(node_address==None):
			return False

		ls_nodes=list(self.peer_nodes.get_nodelist())

		## get address list of nodes
		ls_address = []
		for node in ls_nodes:
			json_node = TypesUtil.string_to_json(node)
			ls_address.append(json_node['address'])
		parent_block = self.processed_head

		## sort ls_address
		sort_address = sorted(ls_address, reverse=True)

		## rid is round id used to get node which is qualified for round proposal
		rid = parent_block['height'] % len(sort_address)
		
		## return verify result	
		return sort_address[rid]==node_address

	def load_chain(self, block_num=10):
		'''
		Database operation: Load latest block_num of chain data
		'''
		ls_chain=self.chain_db.select_block(CHAIN_TABLE)
		chain_size = len(ls_chain)

		if(chain_size<block_num):
			ret_chain = ls_chain
		else:
			ret_chain = ls_chain[chain_size-block_num:]
		
		json_blocks = []
		for block in ret_chain:
			json_data = TypesUtil.string_to_json(block[2])
			if( json_data['hash'] not in json_blocks):
				json_data['status']=block[3]
				json_blocks.append(json_data)
		return json_blocks

	def save_chainInfo(self):
		"""
		Config file operation: save the validator information to static json file
		"""
		chain_info = {}
		chain_info['node_id'] = self.node_id
		chain_info['processed_head'] = self.processed_head['hash']
		chain_info['highest_justified_checkpoint'] = self.highest_justified_checkpoint['hash']
		chain_info['highest_finalized_checkpoint'] = self.highest_finalized_checkpoint['hash']
		chain_info['block_dependencies'] = self.block_dependencies
		chain_info['vote_dependencies'] = self.vote_dependencies
		#chain_info['votes'] = self.votes
		chain_info['vote_count'] = self.vote_count

		if(not os.path.exists(CHAIN_DATA_DIR)):
		    os.makedirs(CHAIN_DATA_DIR)
		FileUtil.JSON_save(CHAIN_DATA_DIR+'/'+CHAIN_INFO, chain_info)

	def load_chainInfo(self):
		"""
		Config file operation: load validator information from static json file
		"""
		if(os.path.isfile(CHAIN_DATA_DIR+'/'+CHAIN_INFO)):
			chain_info = FileUtil.JSON_load(CHAIN_DATA_DIR+'/'+CHAIN_INFO)
			chain_info['processed_head'] = self.get_block(chain_info['processed_head'])
			chain_info['highest_justified_checkpoint'] = self.get_block(chain_info['highest_justified_checkpoint'])
			chain_info['highest_finalized_checkpoint'] = self.get_block(chain_info['highest_finalized_checkpoint'])
			return chain_info
		else:
			return None

	def get_info(self):
		'''
		Get validator information for reference and synchronization
		'''
		validator_info = {}
		validator_info['node_id'] = self.node_id
		validator_info['committee_size'] = self.committee_size
		validator_info['processed_head'] = self.processed_head['hash']
		validator_info['highest_justified_checkpoint'] = self.highest_justified_checkpoint['hash']
		validator_info['highest_finalized_checkpoint'] = self.highest_finalized_checkpoint['hash']		
		validator_info['vote_count'] = self.vote_count

		return validator_info

	def get_status(self):
		'''
		Get validator status for synchronization
		'''
		validator_status = {}
		validator_status['consensus_run'] = self.runConsensus
		validator_status['consensus_status'] = self.statusConsensus

		return validator_status

	def valid_transaction(self, json_transaction):
		"""
		Verify a received json_transaction and append to local transactions pool
		Args:
			@ json_transaction: transacton directionary data
			@ return: True or False
		"""
		## ====================== rebuild transaction ==========================
		dict_transaction = Transaction.get_dict(json_transaction['hash'],
												json_transaction['sender_address'], 
												json_transaction['recipient_address'],
												json_transaction['time_stamp'],
												json_transaction['value'])
		
		## get signature (string) from transaction_json
		sign_str = TypesUtil.hex_to_string(json_transaction['signature'])

		## get node data from self.peer_nodes buffer
		sender_node=self.get_node(json_transaction['sender_address'])
		logger.info(sender_node)

		## ====================== verify transaction ==========================
		## 1) check if a tx comes from the authorized node, like committee members.
		if(sender_node!={}):
		    sender_pk= sender_node['public_key']
		    verify_result = Transaction.verify(sender_pk, sign_str, dict_transaction)
		else:
			verify_result = False

		## 2) check if a tx comes from the same sender in current round. 
		if(verify_result):
			## discard duplicated tx in general scenario
			if(json_transaction not in self.transactions):
					self.transactions.append(json_transaction)
					return True
		else:
			return False
 
	def mine_block(self):
		"""
		Mining task to calculate a valid proof and propose new block
		Args:
			@ json_block: return mined block
		"""
		## set head as last block and used for new block proposal process ----
		last_block = self.processed_head
		
		## Convert json last_block to Block object
		parent_block = Block.json_to_block(last_block)

		## ------------- remove committed transactions in head block -------------
		head_block = self.current_head
		pending_tx = []
		for transaction in self.transactions:
			## search pending txs in head_block.
			if(transaction['hash'] not in head_block['transactions']):
				pending_tx.append(transaction)
		## only keep uncommitted txs.
		self.transactions = copy.copy(pending_tx)

		## ------ choose commit transactions based on COMMIT_TRANS ----------------
		commit_transactions = []
		if( len(self.transactions)<=COMMIT_TRANS ):
			commit_transactions = copy.copy(self.transactions)

		else:
			commit_transactions = copy.copy(self.transactions[:COMMIT_TRANS])

		## --------- only save tx_hash to block['transactions'] -------------------
		ls_tx_hash = []
		for tx in commit_transactions:
			ls_tx_hash.append(tx['hash'])

		## a) ---------- calculate merkle tree root hash of ls_tx_hash ------
		merkle_root = FuncUtil.merkle_root(ls_tx_hash)

		## b) ----------- execute mining task given consensus algorithm ------
		if(self.consensus==ConsensusType.PoW):
			# mining new nonce
			nonce = POW.proof_of_work(last_block['hash'], merkle_root)
			new_block = Block(parent_block, merkle_root, ls_tx_hash, nonce)
		elif(self.consensus==ConsensusType.PoS):
			## get host address
			host_account = None
			if(self.wallet.accounts!=0):
				host_account = self.wallet.accounts[0]
			## propose new block given condition: 1) PoS algorithm or 2) valid round
			if( (POS.proof_of_stake(last_block['hash'], merkle_root, self.node_id, 
									TEST_STAKE_WEIGHT, self.sum_stake )!=0) or
									(self.valid_round(host_account['address'])==True) ):
				## a) generate candidate block with transactions
				new_block = Block(parent_block, merkle_root, ls_tx_hash, self.node_id)	
			else:
				## b) generate empty block without transactions
				new_block = Block(parent_block)		
		else:
			# generate empty block without transactions
			new_block = Block(parent_block)				

		json_block = new_block.to_json()

		# c) --------------- add sender address and signature -----------------
		if(self.wallet.accounts!=0):
			sender = self.wallet.accounts[0]
			sign_data = new_block.sign(sender['private_key'], 'samuelxu999')
			json_block['sender_address'] = sender['address']
			json_block['signature'] = TypesUtil.string_to_hex(sign_data)
		else:
			json_block['sender_address'] = 'Null'
			json_block['signature'] = 'Null'

		return json_block

	def valid_block(self, new_block):
		"""
		Check if a new block from other miner can show valid proof of work
		Args:
			@ new_block: vote json data
			@ return: True or False
		"""
		current_block = new_block

		# get node data from self.peer_nodes buffer
		sender_node = self.get_node(current_block['sender_address'])

		# ======================1: verify block signature ==========================
		if(sender_node==None):
			# unknown sender, drop block
			logger.info("Invalid sender: {}".format(current_block['sender_address']))
			return False

		## rebuild block object given json data
		obj_block = Block.json_to_block(current_block)
		# if check signature failed, drop block
		if( not obj_block.verify(sender_node['public_key'], 
							TypesUtil.hex_to_string(current_block['signature']) ) ):
			logger.info("Invalid signature from sender: {}".format(current_block['sender_address']))
			return

		#=========2: Check that the Proof of Work is correct given current block data =========
		# a) reject block with empty transactions
		if(current_block['transactions']==[]):
			logger.info("Invalid block with empty txs from sender: {}".format(current_block['sender_address']))
			return False

		## b) verify if transactions list has the same merkel root hash as in block['merkle_root']
		ls_tx_hash = current_block['transactions']

		## ---------- calculate merkle tree root hash of dict_transactions ------
		merkle_root = FuncUtil.merkle_root(ls_tx_hash)

		## verify if merkle_root is the same as block data
		if(merkle_root!=current_block['merkle_root']):
			logger.info("Transactions merkel tree root verify fail. Block: {}  sender: {}".format(current_block['hash'],current_block['sender_address']))
			return False

		# c) execute valid proof task given consensus algorithm
		if(self.consensus==ConsensusType.PoW):
			if( not POW.valid_proof(current_block['previous_hash'], current_block['merkle_root'], current_block['nonce']) ):
				logger.info("PoW verify proof fail. Block: {}  sender: {}".format(current_block['hash'],current_block['sender_address']))
				return False
		elif(self.consensus==ConsensusType.PoS):
			## check if a valid PoS proof
			if( not POS.valid_proof(current_block['previous_hash'], current_block['merkle_root'], current_block['nonce'], 
									TEST_STAKE_WEIGHT, self.sum_stake) ):
				logger.info("PoS verify proof fail. Block: {}  sender: {}".format(current_block['hash'],current_block['sender_address']))
				## If not a valid PoS proof, then check if sender has a valid round proof
				if(not self.valid_round(current_block['sender_address'])): 
					logger.info("Round verify proof fail. Block: {}  sender: {}".format(current_block['hash'],current_block['sender_address']))
					return False
		else:
			return False

		return True

	def valid_vote(self, json_vote):
		'''
		Check if a vote from other validator is valid or not
		Args:
			@ json_vote: vote json data
			@ verify_result: True or False
		'''
		# ------------------- verify vote before accept it ------------------
		verify_result = False

		if(json_vote==None or json_vote=='{}'):
			return verify_result

		#rebuild vote object given json data
		new_vote = VoteCheckPoint.json_to_vote(json_vote)

		sign_data = TypesUtil.hex_to_string(json_vote['signature'])

		# get node data from self.peer_nodes buffer
		sender_node=self.get_node(new_vote.sender_address)

		# ====================== verify vote ==========================
		if(sender_node!=None):
			sender_pk = sender_node['public_key']
			verify_result = VoteCheckPoint.verify(sender_pk, sign_data, new_vote.to_dict())

		return verify_result

	def valid_transactions(self, transactions):
		'''
		check if all transactions that are committed in a new block are valid
		Args:
			@ transactions: transactions json list
			@ verify_result: True or False
		'''
		verify_result = True

		tx_pool = []
		for tx in self.transactions:
			tx_pool.append(tx['hash'])

		## each tx_hash to check if it's valid in tx_pool
		for tx_hash in transactions:
			if(tx_hash not in tx_pool):
				verify_result = False
				break
		return verify_result

	def get_parent(self, json_block):
		'''	
		Get the parent block of a given block (json)
		Args:
			@ json_block: block json data
			@ return: parent block json
		'''
		# root block, return None
		if(json_block['height'] == 0):
			return None
		ls_block = self.chain_db.select_block(CHAIN_TABLE, json_block['previous_hash'])
		
		if(ls_block==[]):
			return None
		else:
			return TypesUtil.string_to_json(ls_block[0][2])

	def is_ancestor(self, anc_block, desc_block):
		"""Is a given block an ancestor of another given block?
		Args:
		    anc_hash: ancestor block hash
		    desc_hash: descendant block hash
		"""	
		if(anc_block == None):
			return False

		# search parent
		while( True ):
			if desc_block is None:
			    return False
			if desc_block['hash'] == anc_block['hash']:
			    return True
			desc_block = self.get_parent(desc_block)

	def on_receive(self, json_msg, op_type=0):
		'''
		Call on receiving message: transactions, block and vote
		Args:
			@ json_msg: json message
			@ op_type: operation type given different message
		'''
		# ----------- 0: transaction message processing -----------
		if(op_type ==0):
			ret = self.accept_transaction(json_msg)
		# ----------- 1: block message processing -----------------
		elif(op_type ==1):
			ret = self.accept_block(json_msg)
		# ----------- 2: vote message processing ------------------
		else:
			ret = self.accept_vote(json_msg)

		# If the object was successfully processed, clear dependencies
		if(ret and op_type !=0):
			if(op_type ==1):
				if(json_msg['hash'] in self.block_dependencies):
					for dependency in self.block_dependencies[json_msg['hash']]:
						self.on_receive(dependency, 1)	
					self.remove_dependency(json_msg['hash'], 0)		
				if(json_msg['hash'] in self.vote_dependencies):
					for dependency in self.vote_dependencies[json_msg['hash']]:
						self.on_receive(dependency, 2)	
					self.remove_dependency(json_msg['hash'], 1)	
			else:
				if(json_msg['hash'] in self.vote_dependencies):
					for dependency in self.vote_dependencies[json_msg['hash']]:
						self.on_receive(dependency, 2)	
					self.remove_dependency(json_msg['hash'], 1)
		
		# save chain info to local
		self.save_chainInfo()
		return ret

	def accept_transaction(self, json_tran):
		'''
		Called on processing a transaction message.
		Args:
			@ json_tran: transaction json message
			@ verify_result: return True or False
		'''
		## ====================== verify transaction ==========================
		verify_result = self.valid_transaction(json_tran)

		## add valid tx to self.msg_buf
		if(verify_result):
			self.msg_buf.append([0, json_tran])

		return verify_result

	def accept_block(self, json_block):
		'''
		Called on processing a block message.
		Args:
			@json_block: received block (json)
			@return: True or False
		'''
		# ------------------- verify block before accept it ------------------
		verify_result = False
		if(self.valid_block(json_block)):
			verify_result = self.valid_transactions(json_block['transactions'])

		if(not verify_result):
			return False
		
		# ---------------- accept block given processed status ----------------
		# If the block's parent has not received, add to dependency list
		if(self.get_parent(json_block) == None):
			self.add_dependency(json_block['previous_hash'], json_block)
			return False

		
		# append verified block to local chain, status = 0, processed
		# ------------  add block to buffer --------------
		# self.add_block(json_block, 0)
		self.msg_buf.append([1, json_block, 0])
		self.check_processed_head(json_block)

		return True

	def vote_checkpoint(self, json_block):
		"""
		Called after receiving a block.
		Args:			
			@json_block: last processed block			
			@json_vote: return a vote json message
		"""
		logger.info('Vote for block: {}    height: {}'.format(json_block['hash'], json_block['height']))
		# if( (json_block['height'] % EPOCH_SIZE) != 0):
		if( (json_block['height'] % self.block_epoch) != 0):
			return None

		# get target block object as voting block
		target_block = json_block
		target_obj = Block.json_to_block(target_block)
		# get source block object as justified checkpoint with greatest height
		source_block = self.highest_justified_checkpoint
		source_obj = Block.json_to_block(source_block)

		# If the block is an epoch block of a higher epoch than what we've seen so far
		# This means that it's the first time we see a checkpoint at this height
		# It also means we never voted for any other checkpoint at this height (rule 1)
		if(target_obj.get_epoch(self.block_epoch) <= source_obj.get_epoch(self.block_epoch)):
			#return None
			source_block = self.highest_finalized_checkpoint
			source_obj = Block.json_to_block(source_block)

		# if the target_block is a descendent of the source_block, build a vote
		json_vote={}
		if(self.is_ancestor(source_block, target_block)):
			# get sender information
			sender_node = self.wallet.accounts[0]

			new_vote = VoteCheckPoint(source_block['hash'], target_block['hash'], 
			                        source_obj.get_epoch(self.block_epoch), target_obj.get_epoch(self.block_epoch), sender_node['address'])
			json_vote = new_vote.to_json()

			# sign vote
			sign_data = new_vote.sign(sender_node['private_key'], 'samuelxu999')
			json_vote['signature'] = TypesUtil.string_to_hex(sign_data)

		return json_vote
		
	def accept_vote(self, json_vote):
		'''
		Called on processing a vote message.
		Args:			
			@json_vote: a vote json message			
			@return: True or False
		'''
		# ============================ Check the vote conditions =================================

		# ---------------------------- verify vote before accept it ---------------------------
		verify_result = self.valid_vote(json_vote)
		if(not verify_result):
			logger.info("V:    invalid vote: {}    sender: {}".format(json_vote['hash'], json_vote['sender_address']))
			return False

		#-------------------------- check if source block is valid-----------------------------
		ls_block = self.chain_db.select_block(CHAIN_TABLE, json_vote['source_hash'])
		# If the block has not yet been processed, add to vote_dependencies
		if(ls_block==[]):
			self.add_dependency(json_vote['source_hash'], json_vote, 1)
			logger.info("S1:    not processed block: {}, add to vote_dependencies".format(json_vote['source_hash']))
			return False
		
		source_block = ls_block[0]
		# If the source block is not justified, discard vote
		if(source_block[3]==0):
			logger.info("S2:    not justified block: {}, discard vote".format(source_block[0]))
			return False

		#-------------------------- check if target block is valid-----------------------------
		ls_block = self.chain_db.select_block(CHAIN_TABLE, json_vote['target_hash'])
		# If the block has not yet been processed, add to vote_dependencies
		if(ls_block==[]):
			self.add_dependency(json_vote['target_hash'], json_vote, 1)
			logger.info("T1:    not processed block: {}, add to vote_dependencies".format(json_vote['target_hash']))
			return False
		
		target_block = ls_block[0]

		# -------- Initialize a voter_db for self.votes[vote.sender] if necessary -------------------
		# VoteCheckPoint.new_voter() will create a voter_db and return it.
		if(json_vote['sender_address'] not in self.votes):
			#self.votes[json_vote['sender_address']] = []
			logger.info("Create a voter_db handle for sender: {}".format(json_vote['sender_address']))
			self.votes[json_vote['sender_address']] = VoteCheckPoint.new_voter(json_vote)

		# ============================ Check the slashing conditions =================================
		# voter_db = self.votes[json_vote['sender_address']]
		# then get vote_data by execute voter_db.select_block(voter_name, block_hash)
		vote_data = VoteCheckPoint.get_voter_data(self.votes[json_vote['sender_address']], json_vote)
		# for each past_vote in vote_data to check
		for past_vote in vote_data:
			if past_vote['epoch_target'] == json_vote['epoch_target']:
				# TODO: SLASH
				logger.info("You just got slashed: R1   sender: {}    vote: {}".format(json_vote['sender_address'], 
																					json_vote['hash']))
				return False

			if ((past_vote['epoch_source'] < json_vote['epoch_source'] and
				past_vote['epoch_target'] > json_vote['epoch_target']) or
				(past_vote['epoch_source'] > json_vote['epoch_source'] and
				past_vote['epoch_target'] < json_vote['epoch_target'])):
				# TODO: SLASH
				logger.info("You just got slashed: R2   sender: {}    vote: {}".format(json_vote['sender_address'], 
																					json_vote['hash']))
				return False

		# Add the vote to the map of votes['sender']
		#self.votes[json_vote['sender_address']].append(json_vote)
		# ----------------------------- add vote data to buffer -------------------------------
		# VoteCheckPoint.add_voter_data(self.votes[json_vote['sender_address']], json_vote)
		self.msg_buf.append([2, self.votes[json_vote['sender_address']], json_vote])

		# Calculate votes count
		if json_vote['source_hash'] not in self.vote_count:
			self.vote_count[json_vote['source_hash']] = {}
		self.vote_count[json_vote['source_hash']][json_vote['target_hash']] = \
		self.vote_count[json_vote['source_hash']].get(json_vote['target_hash'], 0) + 1

		# If there are enough votes, set block as justified
		# if (self.vote_count[json_vote['source_hash']][json_vote['target_hash']] > (NUM_VALIDATORS * 2) // 3):
		if (self.vote_count[json_vote['source_hash']][json_vote['target_hash']] > (self.committee_size * 2) // 3):
			target_status = target_block[3]
			# 1) if target was processed, set justified block
			if( target_status==0 ):
				# Mark the target block as 1-justified
				logger.info("Justified target block: {}".format(json_vote['target_hash']))
				self.update_blockStatus(json_vote['target_hash'], 1)
				target_status = 1
			# 2) update highest_justified_checkpoint as target
			if( json_vote['epoch_target'] > Block.json_to_block(self.highest_justified_checkpoint).get_epoch(self.block_epoch) ):
				logger.info("Update highest_justified_checkpoint: {}".format(json_vote['target_hash']))
				self.highest_justified_checkpoint = self.get_block(json_vote['target_hash'])

			# If the source was a direct parent of the target, the source is finalized block
			source_status = source_block[3]
			if( json_vote['epoch_source'] == (json_vote['epoch_target'] - 1) and target_status==1 and source_status!=2):
				# Mark the source block as 2-finalized
				logger.info("Finalized source block: {}".format(json_vote['source_hash']))
				self.highest_finalized_checkpoint = self.get_block(json_vote['source_hash'])
				self.update_blockStatus(json_vote['source_hash'], 2)

		return True

	def check_processed_head(self, new_block):
		'''
		Reorganize the processed_head to stay on the chain with the highest justified checkpoint.
		If we are on wrong chain, reset the head to be the highest descendent
		among the chains containing the highest justified checkpoint.
		Args:
		    new_block: latest block processed.
		'''
		head_block = self.current_head 
		# we are on the right chain, the head is simply the latest block
		if self.is_ancestor(self.highest_justified_checkpoint, head_block):
			if(self.consensus==ConsensusType.PoS):
				# get proof value used for choose current_head
				new_proof=POS.get_proof(new_block['previous_hash'], new_block['merkle_root'], 
										new_block['nonce'], self.sum_stake)
				head_proof=POS.get_proof(head_block['previous_hash'], head_block['merkle_root'], 
										head_block['nonce'], self.sum_stake)
				# head is genesis block or new_block have smaller proof value than current head
				logger.info( "new block sender:  {}".format(new_block['sender_address']))
				logger.info( "head proof:        {} -- new proof:        {}".format(head_proof, new_proof) )
				logger.info( "head block height: {} -- new block height: {}".format(head_block['height'], new_block['height']) )
				
				# 1) new block is 1 larger height, then update current_head to new block 
				if( head_block['height'] == (new_block['height']-1) ):
					self.current_head = new_block
					logger.info("Update current_head: {}    height: {}".format(self.current_head['hash'], 
																				self.current_head['height']) )
					return

				# 2) new block has same height as current head
				if( head_block['height']==new_block['height'] ):
					# A) who holds smaller proof wins
					if(new_proof<head_proof):
						self.current_head = new_block
						logger.info("Update current_head: {}    height: {}".format(self.current_head['hash'], 
																					self.current_head['height']) )
						return

					# B) If they have same proof wins, who has larger nounce (credit) wins
					if( new_proof==head_proof and new_block['nonce']>head_block['nonce'] ):
						self.current_head = new_block
						logger.info("Update current_head: {}    height: {}".format(self.current_head['hash'], 
																					self.current_head['height']) )
			else:
				self.processed_head = new_block
				logger.info("Fix processed_head: {}    height: {}".format(self.processed_head['hash'],
																			self.processed_head['height']) )

	def fix_processed_head(self):
		'''
		Reset processed_head as each block proposal epoch finished:
		1) For no proposed block, generate empty block as current header
		2) otherwise, directly fixed processed_head
		3) remove committed transactions from local txs pool 
		4) update chaininfo and save into local file
		'''
		if(self.consensus==ConsensusType.PoS):
			# 1) if none of validator propose block, use empty block as header
			if(self.processed_head == self.current_head):
				#generate empty block
				last_block = self.processed_head
				parent_block = Block.json_to_block(last_block)
				json_block = Block(parent_block).to_json()
				json_block['sender_address'] = 'Null'
				json_block['signature'] = 'Null'
				# ------------  add block to buffer --------------
				# self.add_block(json_block, 0)
				self.msg_buf.append([1, json_block, 0])

				self.current_head = json_block
				logger.info("Set current_head as emptyblock: {}".format(self.current_head))
			
			# 2) set processed_head as current_head
			self.processed_head = self.current_head

			## 3) ------------ Add committed txs into msg buffer for furture update -------
			for tx_hash in self.processed_head['transactions']:
				self.msg_buf.append([3, tx_hash, self.processed_head['hash']])

			# 4) remove committed transactions in head block
			pending_tx = []
			for transaction in self.transactions:
				if(transaction['hash'] not in self.processed_head['transactions']):
					pending_tx.append(transaction)
					# self.transactions.remove(transaction)
			self.transactions = copy.copy(pending_tx)

			logger.info("Fix processed_head: {}    height: {}".format(self.processed_head['hash'],
																		self.processed_head['height']) )
			# 5) update chaininfo and save into local file
			self.save_chainInfo()	

	def add_dependency(self, hash_value, json_data, op_type=0):
		'''
		If we processed an object but did not receive some dependencies
		needed to process it, save it to be processed later
		Args:
			@ hash_value: hash value
			@ json_data: json data
			@ op_type: operation type given different message
		'''
		if(op_type ==0):
			if(hash_value not in self.block_dependencies):
				self.block_dependencies[hash_value] = []
			self.block_dependencies[hash_value].append(json_data)
		else:
			if(hash_value not in self.vote_dependencies):
				self.vote_dependencies[hash_value] = []
			self.vote_dependencies[hash_value].append(json_data)
	
	def remove_dependency(self, hash_value, op_type=0):
		'''
		If we processed an object, then remove it from dependencies
		Args:
			@ hash_value: hash value
			@ json_data: json data
			@ op_type: operation type given different message
		'''
		if(op_type ==0):
			if(hash_value in self.block_dependencies):
				del self.block_dependencies[hash_value]
		else:
			if(hash_value in self.vote_dependencies):
				del self.vote_dependencies[hash_value]

