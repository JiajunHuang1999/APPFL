import os
import torch
import torchvision
from mpi4py import MPI
from typing import Optional
from appfl.config import *
from appfl.misc.data import Dataset
from omegaconf import DictConfig
from .utils.transform import test_transform, train_transform
from .utils.partition import iid_partition, class_noiid_partition, dirichlet_noiid_partition

def get_cifar10(comm: Optional[MPI.Comm], cfg: DictConfig, partition: string = "iid", visualization: bool = True, **kwargs):
    comm_rank = comm.Get_rank() if comm is not None else 0
    num_clients = cfg.num_clients

    # Get the download directory for dataset
    dir = os.getcwd() + "/datasets/RawData"

    # Root download the data if not already available.
    if comm_rank == 0:
        test_data_raw = torchvision.datasets.CIFAR10(dir, download=True, train=False, transform=test_transform("CIFAR10"))
    if comm is not None:
        comm.Barrier()
    if comm_rank > 0:
        test_data_raw = torchvision.datasets.CIFAR10(dir, download=False, train=False, transform=test_transform("CIFAR10"))

    # Obtain the testdataset
    test_data_input = []
    test_data_label = []
    for idx in range(len(test_data_raw)):
        test_data_input.append(test_data_raw[idx][0].tolist())
        test_data_label.append(test_data_raw[idx][1])
    test_dataset = Dataset(torch.FloatTensor(test_data_input), torch.tensor(test_data_label))

    # Training data for multiple clients
    train_data_raw = torchvision.datasets.CIFAR10(dir, download=False, train=True, transform=train_transform("CIFAR10"))

    # Obtain the visualization output filename
    if visualization:
        dir = cfg.output_dirname
        if os.path.isdir(dir) == False:
            os.makedirs(dir, exist_ok=True)
        output_filename = f"CIFAR10_{num_clients}clients_{partition}_distribution"
        file_ext = ".pdf"
        filename = dir + "/%s%s" % (output_filename, file_ext)
        uniq = 1
        while os.path.exists(filename):
            filename = dir + "/%s_%d%s" % (output_filename, uniq, file_ext)
            uniq += 1
    else: filename = None

    # Partition the dataset
    if partition == "iid":
        train_datasets = iid_partition(train_data_raw, num_clients, visualization=visualization and comm_rank==0, output=filename)
    elif partition == "class_noiid":
        train_datasets = class_noiid_partition(train_data_raw, num_clients, visualization=visualization and comm_rank==0, output=filename, **kwargs)
    elif partition == "dirichlet_noiid":
        train_datasets = dirichlet_noiid_partition(train_data_raw, num_clients, visualization=visualization and comm_rank==0, output=filename, **kwargs)
    return train_datasets, test_dataset
    