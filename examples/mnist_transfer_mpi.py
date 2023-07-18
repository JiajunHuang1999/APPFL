import os
import time
import torch
import argparse
import torchvision
import numpy as np
import appfl.run_mpi_async as rma
import appfl.run_serial as rs
import appfl.run_mpi_transfer as rm
from mpi4py import MPI
from appfl.config import *
from appfl.misc.data import *
from appfl.misc.utils import *
from models.utils import get_model
from torchvision.transforms import ToTensor

""" read arguments """

parser = argparse.ArgumentParser()

parser.add_argument("--device", type=str, default="cpu")

## dataset
parser.add_argument("--dataset", type=str, default="MNIST")
parser.add_argument("--num_channel", type=int, default=1)
parser.add_argument("--num_classes", type=int, default=10)
parser.add_argument("--num_pixel", type=int, default=28)
parser.add_argument("--model", type=str, default="CNN")
parser.add_argument('--train_data_batch_size', type=int, default=128)   
parser.add_argument('--test_data_batch_size', type=int, default=128)  

## clients
# parser.add_argument("--num_clients", type=int, default=2)
parser.add_argument("--client_optimizer", type=str, default="Adam")
parser.add_argument("--client_lr", type=float, default=1e-3)
# parser.add_argument("--num_local_epochs", type=int, default=1)
parser.add_argument('--num_local_epochs', type=int, default=1)    

## server
parser.add_argument("--num_epochs", type=int, default=20)
parser.add_argument("--server", type=str, default="ServerFedAvg")
parser.add_argument("--server_lr", type=float, required=False)
parser.add_argument("--mparam_1", type=float, required=False)
parser.add_argument("--mparam_2", type=float, required=False)
parser.add_argument("--adapt_param", type=float, required=False)


args = parser.parse_args()

if torch.cuda.is_available():
    args.device = "cuda"

def get_data(comm: MPI.Comm):
    dir = os.getcwd() + "/datasets/RawData"

    comm_rank = comm.Get_rank()

    # Root download the data if not already available.
    if comm_rank == 0:
        # test data for a server
        test_data_raw = eval("torchvision.datasets." + args.dataset)(
            dir, download=True, train=False, transform=ToTensor()
        )

    comm.Barrier()
    if comm_rank > 0:
        # test data for a server
        test_data_raw = eval("torchvision.datasets." + args.dataset)(
            dir, download=False, train=False, transform=ToTensor()
        )

    test_data_input = []
    test_data_label = []
    for idx in range(len(test_data_raw)):
        test_data_input.append(test_data_raw[idx][0].tolist())
        test_data_label.append(test_data_raw[idx][1])

    test_dataset = Dataset(
        torch.FloatTensor(test_data_input), torch.tensor(test_data_label)
    )

    # training data for multiple clients
    train_data_raw = eval("torchvision.datasets." + args.dataset)(
        dir, download=False, train=True, transform=ToTensor()
    )

    split_train_data_raw = np.array_split(range(len(train_data_raw)), args.num_clients)
    train_datasets = []
    for i in range(args.num_clients-1):

        train_data_input = []
        train_data_label = []
        for idx in split_train_data_raw[i]:
            train_data_input.append(train_data_raw[idx][0].tolist())
            train_data_label.append(train_data_raw[idx][1])

        train_datasets.append(
            Dataset(
                torch.FloatTensor(train_data_input),
                torch.tensor(train_data_label),
            )
        ) 
    
    target_train_data_input = []
    target_train_data_label = []
    for idx in split_train_data_raw[args.num_clients-1]:
        target_train_data_input.append(train_data_raw[idx][0].tolist())
        target_train_data_label.append(train_data_raw[idx][1])
    target_train_datasets = []
    target_train_datasets.append(
        Dataset(
            torch.FloatTensor(target_train_data_input),
            torch.tensor(target_train_data_label)
        )
    )
    return train_datasets, test_dataset, target_train_datasets

## Run
def main():

    comm = MPI.COMM_WORLD
    comm_rank = comm.Get_rank()
    comm_size = comm.Get_size()

    assert comm_size > 1, "This script requires the toal number of processes to be greater than one!"
    args.num_clients = comm_size - 1

    """ Configuration """
    cfg = OmegaConf.structured(Config(fed=FedAsync()))

    cfg.device = args.device
    cfg.reproduce = True
    if cfg.reproduce == True:
        set_seed(1)

    ## clients
    cfg.num_clients = args.num_clients
    cfg.fed.args.optim = args.client_optimizer
    cfg.fed.args.optim_args.lr = args.client_lr
    cfg.fed.args.num_local_epochs = args.num_local_epochs
    cfg.train_data_shuffle = True

    ## server
    cfg.fed.servername = args.server
    cfg.num_epochs = args.num_epochs

    ## outputs

    cfg.use_tensorboard = False

    cfg.save_model_state_dict = False

    cfg.output_dirname = "./outputs_%s_%s_%s" % (
        args.dataset,
        args.server,
        args.client_optimizer,
    )
    if args.server_lr != None:
        cfg.fed.args.server_learning_rate = args.server_lr
        cfg.output_dirname += "_ServerLR_%s" % (args.server_lr)

    if args.adapt_param != None:
        cfg.fed.args.server_adapt_param = args.adapt_param
        cfg.output_dirname += "_AdaptParam_%s" % (args.adapt_param)

    if args.mparam_1 != None:
        cfg.fed.args.server_momentum_param_1 = args.mparam_1
        cfg.output_dirname += "_MParam1_%s" % (args.mparam_1)

    if args.mparam_2 != None:
        cfg.fed.args.server_momentum_param_2 = args.mparam_2
        cfg.output_dirname += "_MParam2_%s" % (args.mparam_2)

    cfg.output_filename = "result"


    start_time = time.time()

    """ User-defined model """
    model = get_model(args)
    loss_fn = torch.nn.CrossEntropyLoss()   

    ## loading models
    cfg.load_model = False
    if cfg.load_model == True:
        cfg.load_model_dirname = "./save_models"
        cfg.load_model_filename = "Model"
        model = load_model(cfg)

    """ User-defined data """
    # train_datasets, test_dataset = get_data(comm)
    train_datasets, test_dataset, target_train_datasets = get_data(comm)

    ## Sanity check for the user-defined data
    if cfg.data_sanity == True:
        data_sanity_check(
            train_datasets, test_dataset, args.num_channel, args.num_pixel
        )

    print(
        "-------Loading_Time=",
        time.time() - start_time,
    )

    """ saving models """
    cfg.save_model = False
    if cfg.save_model == True:
        cfg.save_model_dirname = "./save_models"
        cfg.save_model_filename = "Model"

    """ Running """
    if comm_rank == 0:
        rm.run_server(
            cfg, comm, model, loss_fn, args.num_clients, test_dataset, args.dataset, target_train_datasets
        )
    else:
        # assert comm_size == args.num_clients + 1
        rm.run_client(
            cfg, comm, model, loss_fn, args.num_clients-1, train_datasets, test_dataset
        )
    print("------DONE------", comm_rank)


if __name__ == "__main__":
    main()


# To run CUDA-aware MPI with n clients:
# mpiexec -np n+1 --mca opal_cuda_support 1 python ./mnist_transfer_mpi.py
# To run MPI with n clients:
# mpiexec -np n+1 python ./mnist_transfer_mpi.py
# mpiexec -np 3 python ./mnist_transfer_mpi.py
