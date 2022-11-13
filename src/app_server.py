'''
========================
app_server module
========================
Created on Nov.11, 2022
@author: Xu Ronghua
@Email:  rxu22@binghamton.edu
@TaskDescription: This module provide application server side api
'''

import sys
import time
import datetime
import json
import threading
import logging
import asyncio
import socket
from flask import Flask, jsonify, render_template
from flask import abort,make_response,request
from argparse import ArgumentParser
from utils.utilities import TypesUtil, FileUtil
from utils.Client_RPC import Client_RPC

logger = logging.getLogger(__name__)

# ================================= Instantiate the server =====================================
app = Flask(__name__)

#===================================== Web App handler ===================================
@app.route('/')
def info():
    ## query information of neighbors
    target_address = args.bootstrapnode
    neighbors = Client_instace.query_neighbors(target_address)['neighbors']

    ls_peers = []

    for node in neighbors:
        node_info={}
        node_info['url']="{}:80{}".format(node[0], str(node[1])[-2:])

        ## get account address
        _account = Client_instace.query_account(node_info['url'])['info']
        node_info['account']=str(_account['address'])

        ## get validator information
        _validator = Client_instace.query_validator(node_info['url'])
        node_info['node_id']=str(_validator['node_id'])

        ls_peers.append(node_info)


    return render_template('info.html', posts = [ls_peers, len(ls_peers)])

@app.route('/validator', methods=['GET', 'POST'])
def validator():
    ret_posts = ['NULL']
    ## get params from request
    if request.method == 'POST':
        node_url = request.form.get('node_url')
        ret_posts[0]=node_url
        
        ## get validator information
        _validator = Client_instace.query_validator(node_url)

        ret_posts.append(_validator)

        ## get vote list
        ls_vote = []
        for source, value in _validator['vote_count'].items():
            for target, vote in value.items():
                ls_vote.append([source, target, vote])

        ret_posts.append(ls_vote)

    return render_template('validator.html', posts = ret_posts)

def define_and_get_arguments(args=sys.argv[1:]):
    parser = ArgumentParser(description="Run microchain websocket server.")

    parser.add_argument("--debug", action="store_true", 
                        help="if set, debug model will be used.")

    parser.add_argument("--threaded", action="store_true", 
                        help="if set, support threading request.")

    parser.add_argument('-p', '--port', default=8680, type=int, 
                        help="port to listen on.")

    parser.add_argument("--bootstrapnode", default='128.226.88.197:8080', type=str, 
                        help="bootstrap node address format[ip:port] to join the network.")

    args = parser.parse_args()

    return args

## ****************************** Main function ***********************************
if __name__ == '__main__':
    FORMAT = "%(asctime)s %(levelname)s %(filename)s(l:%(lineno)d) - %(message)s"
    # FORMAT = "%(asctime)s %(levelname)s | %(message)s"
    LOG_LEVEL = logging.INFO
    logging.basicConfig(format=FORMAT, level=LOG_LEVEL)

    ## get arguments
    args = define_and_get_arguments()

    ## initialize Client_RPC instance
    Client_instace = Client_RPC(args.bootstrapnode)

    ## -------------------------------- run app server ----------------------------------------
    app.run(host='0.0.0.0', port=args.port, debug=args.debug, threaded=args.threaded)


