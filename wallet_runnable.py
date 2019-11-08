import asyncio
import clvm
import qrcode
from decorations import print_leaf, divider, prompt, start_list, close_list, selectable, informative
from pyzbar.pyzbar import decode
from PIL import Image
from chiasim.hashable import Coin
from chiasim.clients.ledger_sim import connect_to_ledger_sim
from chiasim.wallet.deltas import additions_for_body, removals_for_body
from chiasim.hashable.Body import BodyList
from clvm_tools import binutils
from chiasim.hashable import Program, ProgramHash
from binascii import hexlify
from wallet import ap_wallet_a_functions
from wallet.wallet import Wallet


def view_funds(wallet):
    print("Current balance: " + str(wallet.temp_balance))
    print("UTXOs: ", end="")
    print([x.amount for x in wallet.temp_utxos if x.amount > 0])


def add_contact(wallet):
    name = input(prompt + "What is the new contact's name? ")
    puzzlegeneratorstring = input(prompt + "What is their ChiaLisp puzzlegenerator: ")
    puzzlegenerator = binutils.assemble(puzzlegeneratorstring)
    wallet.add_contact(name, puzzlegenerator, 0, None)


def view_contacts(wallet):
    print(start_list)
    for name, details in wallet.contacts:
        print(name)
    print(close_list)


def print_my_details(wallet):
    print(informative + " Name: " + wallet.name)
    print(informative + " Puzzle Generator: ")
    print(informative + " " + wallet.puzzle_generator)
    pubkey = "%s" % hexlify(
        wallet.get_next_public_key().serialize()).decode('ascii')
    print(informative + " New pubkey: " + pubkey)
    print(informative + " Generator hash identifier:")
    print(informative + " " + wallet.puzzle_generator_id)
    print(informative + " Single string: " + wallet.name + ":" +
          wallet.puzzle_generator_id + ":" + pubkey)


def make_QR(wallet):
    print(divider)
    pubkey = hexlify(wallet.get_next_public_key().serialize()).decode('ascii')
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(wallet.name + ":" + wallet.puzzle_generator_id + ":" + pubkey)
    qr.make(fit=True)
    img = qr.make_image()
    fn = input("Input file name: ")
    if fn.endswith(".jpg"):
        img.save(fn)
    else:
        img.save(fn + ".jpg")
    print("QR code created in '" + fn + ".jpg'")


def read_qr(wallet):
    amount = -1
    if wallet.current_balance <= 0:
        print("You need some money first")
        return None
    print("Input filename of QR code: ")  # this'll have to do for now
    fn = input()
    decoded = decode(Image.open(fn))
    name, type, pubkey = QR_string_parser(str(decoded[0].data))
    if type not in wallet.generator_lookups:
        print("Unknown generator - please input the source.")
        source = input("Source: ")
        if str(ProgramHash(Program(binutils.assemble(source)))) != "0x" + type:
            print("source not equal to ID")
            breakpoint()
            return
        else:
            wallet.generator_lookups[type] = source
    while amount > wallet.temp_balance or amount <= 0:
        amount = input("Amount: ")
        if amount == "q":
            return
        if not amount.isdigit():
            amount = -1
        amount = int(amount)
    args = binutils.assemble("(0x" + pubkey + ")")
    program = Program(clvm.eval_f(clvm.eval_f, binutils.assemble(
        wallet.generator_lookups[type]), args))
    puzzlehash = ProgramHash(program)
    return wallet.generate_signed_transaction(amount, puzzlehash)


def QR_string_parser(input):
    arr = input.split(":")
    name = arr[0]
    generatorID = arr[1]
    pubkey = arr[2]
    if pubkey.endswith("'"):
        pubkey = pubkey[:-1]
    return name, generatorID, pubkey


def set_name(wallet):
    selection = input("Enter a new name: ")
    wallet.set_name(selection)


def make_payment(wallet):
    amount = -1
    if wallet.current_balance <= 0:
        print("You need some money first")
        return None
    qr = input("Enter QR string: ")
    name, type, pubkey = QR_string_parser(qr)
    if type not in wallet.generator_lookups:
        print("Unknown generator - please input the source.")
        source = input("Source: ")
        if str(ProgramHash(Program(binutils.assemble(source)))) != type:
            print("source not equal to ID")
            breakpoint()
            return
        else:
            wallet.generator_lookups[type] = source
    while amount > wallet.temp_balance or amount < 0:
        amount = input("Amount: ")
        if amount == "q":
            return
        if not amount.isdigit():
            amount = -1
        amount = int(amount)
    args = binutils.assemble("(0x" + pubkey + ")")
    program = Program(clvm.eval_f(clvm.eval_f, binutils.assemble(
        wallet.generator_lookups[type]), args))
    puzzlehash = ProgramHash(program)
    # print(puzzlehash)
    # breakpoint()
    return wallet.generate_signed_transaction(amount, puzzlehash)


async def select_smart_contract(wallet, ledger_api):
    print("Select a smart contract: ")
    print(selectable + " 1: Authorised Payees")
    print(selectable + " 2: Other ChiaLisp Puzzle")
    choice = input()
    if choice == "1":
        if wallet.temp_balance <= 0:
            print("You need some money first")
            return None
        # TODO: add a strict format checker to input here (and everywhere tbh)
        # Actual puzzle lockup/spend
        a_pubkey = wallet.get_next_public_key().serialize()
        b_pubkey = input("Enter recipient's pubkey: 0x")
        amount = -1
        while amount > wallet.temp_balance or amount < 0:
            amount = input("Enter amount to give recipient: ")
            if amount == "q":
                return
            if not amount.isdigit():
                amount = -1
            amount = int(amount)

        APpuzzlehash = ap_wallet_a_functions.ap_get_new_puzzlehash(
            a_pubkey, b_pubkey)
        spend_bundle = wallet.generate_signed_transaction(amount, APpuzzlehash)
        await ledger_api.push_tx(tx=spend_bundle)
        print()
        print(informative + "AP Puzzlehash is: " + str(APpuzzlehash))
        print(informative + "Pubkey used is: " + hexlify(a_pubkey).decode('ascii'))
        sig = ap_wallet_a_functions.ap_sign_output_newpuzzlehash(
            APpuzzlehash, wallet, a_pubkey)
        print(informative + "Approved change signature is: " + str(sig.sig))
        print(informative + "Single string: " + str(APpuzzlehash) + ":" +
              hexlify(a_pubkey).decode('ascii') + ":" + str(sig.sig))

        # Authorised puzzle printout for AP Wallet
        print("Enter pubkeys of authorised recipients, press 'q' to finish")
        while choice != "q":
            singlestr = input("Enter recipient QR string: ")
            if singlestr == "q":
                return
            name, type, pubkey = QR_string_parser(singlestr)
            if type not in wallet.generator_lookups:
                print("Unknown generator - please input the source.")
                source = input("Source: ")
                if str(ProgramHash(Program(binutils.assemble(source)))) != type:
                    print("source not equal to ID")
                    breakpoint()
                    return
                else:
                    wallet.generator_lookups[type] = source
            args = binutils.assemble("(0x" + pubkey + ")")
            program = Program(clvm.eval_f(clvm.eval_f, binutils.assemble(
                wallet.generator_lookups[type]), args))
            puzzlehash = ProgramHash(program)
            print()
            #print("Puzzle: " + str(puzzlehash))
            sig = wallet.sign(puzzlehash, a_pubkey)
            #print("Signature: " + str(sig.sig))
            print(informative + "Single string for AP Wallet: " + name +
                  ":" + str(puzzlehash) + ":" + str(sig.sig))
            choice = input("Press 'c' to continue, or 'q' to quit to menu: ")
    elif choice == "2":
        puzzle_source = input("Enter a ChiaLisp puzzle to lock a coin up with: ")
        if puzzle_source == "q":
            return
        try:
            puzhash = ProgramHash(Program(binutils.assemble(puzzle_source)))
            amount = input("Enter amount for new coin: ")
            amount = int(amount)
            spend_bundle = wallet.generate_signed_transaction(amount, puzhash)
            await ledger_api.push_tx(tx=spend_bundle)
        except Exception as err:
            print(err)


async def new_block(wallet, ledger_api):
    coinbase_puzzle_hash = wallet.get_new_puzzlehash()
    fees_puzzle_hash = wallet.get_new_puzzlehash()
    r = await ledger_api.next_block(coinbase_puzzle_hash=coinbase_puzzle_hash, fees_puzzle_hash=fees_puzzle_hash)
    body = r["body"]
    # breakpoint()
    most_recent_header = r['header']
    # breakpoint()
    additions = list(additions_for_body(body))
    removals = removals_for_body(body)
    removals = [Coin.from_bytes(await ledger_api.hash_preimage(hash=x)) for x in removals]
    wallet.notify(additions, removals)
    return most_recent_header


async def update_ledger(wallet, ledger_api, most_recent_header):
    if most_recent_header is None:
        r = await ledger_api.get_all_blocks()
    else:
        r = await ledger_api.get_recent_blocks(most_recent_header=most_recent_header)
    update_list = BodyList.from_bytes(r)
    for body in update_list:
        additions = list(additions_for_body(body))
        print(additions)
        removals = removals_for_body(body)
        removals = [Coin.from_bytes(await ledger_api.hash_preimage(hash=x)) for x in removals]
        wallet.notify(additions, removals)


async def main():
    ledger_api = await connect_to_ledger_sim("localhost", 9868)
    selection = ""
    wallet = Wallet()
    print(divider)
    print_leaf()
    most_recent_header = None
    while selection != "q":
        print(divider)
        view_funds(wallet)
        print(divider)
        print(start_list)
        print("Select a function:")
        print(selectable + " 1: Make Payment")
        print(selectable + " 2: Get Update")
        print(selectable + " 3: *GOD MODE* Commit Block / Get Money")
        print(selectable + " 4: Print my details for somebody else")
        print(selectable + " 5: Set my wallet name")
        print(selectable + " 6: Make QR code")
        print(selectable + " 7: Make Smart Contract")
        print(selectable + " 8: Payment to QR code")
        print(selectable + " q: Quit")
        print(close_list)
        selection = input(prompt)
        if selection == "1":
            r = make_payment(wallet)
            if r is not None:
                await ledger_api.push_tx(tx=r)
        elif selection == "2":
            await update_ledger(wallet, ledger_api, most_recent_header)
        elif selection == "3":
            most_recent_header = await new_block(wallet, ledger_api)
        elif selection == "4":
            print_my_details(wallet)
        elif selection == "5":
            set_name(wallet)
        elif selection == "6":
            make_QR(wallet)
        elif selection == "7":
            await select_smart_contract(wallet, ledger_api)
        elif selection == "8":
            r = read_qr(wallet)
            if r is not None:
                await ledger_api.push_tx(tx=r)


run = asyncio.get_event_loop().run_until_complete
run(main())
