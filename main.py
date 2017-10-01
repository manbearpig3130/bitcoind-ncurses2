# Copyright (c) 2014-2017 esotericnonsense (Daniel Edgecumbe)
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://opensource.org/licenses/mit-license.php

import argparse
import os
import asyncio
import datetime

import rpc
import interface
import modes
import splash
import header
import footer
import monitor
import peers
import block
import transaction
import net
import wallet


async def keypress_loop(window, callback, resize_callback):
    async def handle_keypress(key):
        if key == "KEY_RESIZE":
            y, x = window.getmaxyx()
            await resize_callback(y, x)
            return

        if len(key) == 1 and key.lower() == "q":
            raise Exception("Quitting.")

        key = await callback(key)
        if key is not None:
            # Unhandled key. Don't care.
            pass

    while True:
        # This is basically spinning which is really annoying.
        # TODO: find a way of having async blocking getch/getkey.
        try:
            key = window.getkey()
        except Exception:
            await asyncio.sleep(0.05)
            continue

        await handle_keypress(key)


async def poll_client(client, method, callback, sleeptime, params=None):
    # Allow the rest of the program to start.
    await asyncio.sleep(0.1)

    while True:
        j = await client.request(method, params=params)
        await callback(method, j)
        await asyncio.sleep(sleeptime)


async def tick(callback, sleeptime):
    # Allow the rest of the program to start.
    await asyncio.sleep(0.1)

    while True:
        dt = datetime.datetime.utcnow()
        await callback(dt)
        await asyncio.sleep(sleeptime)


def initialize():
    # parse commandline arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--datadir",
                        help="path to bitcoin datadir [~/.bitcoin/]",
                        default=os.path.expanduser("~/.bitcoin/"))
    parser.add_argument("--no-splash",
                        help="whether to disable the splash screen [False]",
                        action='store_true',
                        dest="nosplash",
                        default=False)
    args = parser.parse_args()

    url = rpc.get_url_from_datadir(args.datadir)
    auth = rpc.get_auth_from_datadir(args.datadir)
    client = rpc.BitcoinRPCClient(url, auth)

    return client, args.nosplash


def check_disablewallet(client):
    """ Check if the wallet is enabled. """

    # Ugly, a synchronous RPC request mechanism would be nice here.
    x = asyncio.gather(client.request("getwalletinfo"))
    loop = asyncio.get_event_loop()
    loop.run_until_complete(x)

    try:
        x.result()[0]["result"]["walletname"]
    except (KeyError, TypeError):
        return True

    return False


def create_tasks(client, window, nosplash):
    headerview = header.HeaderView()
    footerview = footer.FooterView()

    modehandler = modes.ModeHandler(
        (headerview.on_mode_change, footerview.on_mode_change, ),
    )

    splashview = splash.SplashView(modehandler.set_mode)

    monitorview = monitor.MonitorView(client)
    peerview = peers.PeersView()

    transactionstore = transaction.TransactionStore(client)
    transactionview = transaction.TransactionView(transactionstore)

    blockstore = block.BlockStore(client)
    blockview = block.BlockView(
        blockstore,
        transactionview.set_txid,
        modehandler.set_mode,
    )

    netview = net.NetView()
    walletview = wallet.WalletView(
        transactionview.set_txid,
        modehandler.set_mode,
    )

    modehandler.add_callback("monitor", monitorview.on_mode_change)
    modehandler.add_callback("peers", peerview.on_mode_change)
    modehandler.add_callback("block", blockview.on_mode_change)
    modehandler.add_callback("transaction", transactionview.on_mode_change)
    modehandler.add_callback("net", netview.on_mode_change)
    modehandler.add_callback("wallet", walletview.on_mode_change)

    modehandler.add_keypress_handler("block", blockview.handle_keypress)
    modehandler.add_keypress_handler("transaction", transactionview.handle_keypress)
    modehandler.add_keypress_handler("wallet", walletview.handle_keypress)

    async def on_nettotals(key, obj):
        await headerview.on_nettotals(key, obj)
        await netview.on_nettotals(key, obj)

    async def on_bestblockhash(key, obj):
        await monitorview.on_bestblockhash(key, obj)
        await blockview.on_bestblockhash(key, obj)

    async def on_peerinfo(key, obj):
        await headerview.on_peerinfo(key, obj)
        await peerview.on_peerinfo(key, obj)

    async def on_tick(dt):
        await footerview.on_tick(dt)
        await monitorview.on_tick(dt)

    async def on_window_resize(y, x):
        interface.check_min_window_size(y, x)

        await splashview.on_window_resize(y, x)
        await headerview.on_window_resize(y, x)
        await footerview.on_window_resize(y, x)
        await monitorview.on_window_resize(y, x)
        await peerview.on_window_resize(y, x)
        await blockview.on_window_resize(y, x)
        await transactionview.on_window_resize(y, x)
        await netview.on_window_resize(y, x)
        await walletview.on_window_resize(y, x)

    ty, tx = window.getmaxyx()
    tasks = [
        poll_client(client, "getbestblockhash",
                    on_bestblockhash, 1.0),
        poll_client(client, "getblockchaininfo",
                    headerview.on_blockchaininfo, 5.0),
        poll_client(client, "getnetworkinfo",
                    headerview.on_networkinfo, 5.0),
        poll_client(client, "getnettotals",
                    on_nettotals, 5.0),
        poll_client(client, "getpeerinfo",
                    on_peerinfo, 5.0),
        poll_client(client, "getmempoolinfo",
                    monitorview.on_mempoolinfo, 5.0),
        poll_client(client, "listsinceblock",
                    walletview.on_sinceblock, 5.0),
        poll_client(client, "estimatesmartfee",
                    monitorview.on_estimatesmartfee, 15.0, params=[2]),
        poll_client(client, "estimatesmartfee",
                    monitorview.on_estimatesmartfee, 15.0, params=[5]),
        poll_client(client, "estimatesmartfee",
                    monitorview.on_estimatesmartfee, 15.0, params=[10]),
        # This is a bit lazy because we could just do it once and calculate it.
        poll_client(client, "uptime",
                    monitorview.on_uptime, 5.0, params=[10]),
        tick(on_tick, 1.0),
        keypress_loop(window, modehandler.handle_keypress, on_window_resize),
        on_window_resize(ty, tx),
        splashview.draw(nosplash),
    ]

    if not check_disablewallet(client):
        tasks.append(
            poll_client(client, "getwalletinfo", headerview.on_walletinfo, 1.0)
        )

    return tasks


def mainfn():
    client, nosplash = initialize()


    try:
        window = interface.init_curses()

        tasks = create_tasks(client, window, nosplash)

        loop = asyncio.get_event_loop()
        t = asyncio.gather(*tasks)
        loop.run_until_complete(t)

    finally:
        try:
            loop.close()
        except BaseException:
            pass
        interface.end_curses()


if __name__ == "__main__":
    mainfn()
