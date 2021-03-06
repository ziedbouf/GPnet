from __future__ import division
from abc import ABCMeta, abstractmethod
import numpy as np
import matplotlib.pyplot as pl
import scipy.optimize as so
import scipy.linalg as sl
import scipy.sparse as ss
import matplotlib.patches as mpatches
import matplotlib.lines as mlines
import networkx as nx
import pandas as pd
import random
from scipy.special import erf
import time

# %%

# circles
blue_circle = mlines.Line2D(
    [], [], color="blue", marker="o", linestyle="None", markersize=10
)
red_circle = mlines.Line2D(
    [], [], color="red", marker="o", linestyle="None", markersize=10
)
green_circle = mlines.Line2D(
    [], [], color="green", marker="o", linestyle="None", markersize=10
)
gray_circle = mlines.Line2D(
    [], [], color="gray", marker="o", linestyle="None", markersize=10
)
# triangles
blue_triangle = mlines.Line2D(
    [], [], color="blue", marker="v", linestyle="None", markersize=10
)
red_triangle = mlines.Line2D(
    [], [], color="red", marker="v", linestyle="None", markersize=10
)
green_triangle = mlines.Line2D(
    [], [], color="green", marker="v", linestyle="None", markersize=10
)
# squares
blue_square = mlines.Line2D(
    [], [], color="blue", marker="s", linestyle="None", markersize=10
)
red_square = mlines.Line2D(
    [], [], color="red", marker="s", linestyle="None", markersize=10
)
green_square = mlines.Line2D(
    [], [], color="green", marker="s", linestyle="None", markersize=10
)


# Values required for approximating the logistic sigmoid by
# error functions. coefs are obtained via:
# x = np.array([0, 0.6, 2, 3.5, 4.5, np.inf])
# b = logistic(x)
# A = (erf(np.dot(x, self.lambdas)) + 1) / 2
# coefs = lstsq(A, b)[0]
# LAMBDAS = np.array([0.41, 0.4, 0.37, 0.44, 0.39])[:, np.newaxis]
LAMBDAS = np.array([0.41, 0.4, 0.37, 0.44, 0.39])
COEFS = np.array(
    [-1854.8214151, 3516.89893646, 221.29346712, 128.12323805, -2010.49422654]
)[:, np.newaxis]


# %%
class GPnet:
    __metaclass_ = "GPnet"
    """ GPnet class cointains common attributes and methods for GPnetClassifier 
    and GPnetRegressor
    
    
    Attributes
    ----------
    
    Graph : network Graph
        NetworkX Graph on which regression/classification is made, if no graph
        is provided random regular graph is generated
    totnodes : int
        total number of nodes (for random graph generation)
    ntrain : int
        number of training nodes
    ntest : int
        number of test nodes
    deg : int
        connectivity degree (for random graph generation)
    seed : int
        seed for random number generation
    training_nodes: list
        list of nodes that are used for training
    test_nodes: list
        list of test nodes
    training_values: pandas Series (will be changed in future)
        training labels
    theta: list
        list of kernel parameters [a, b, c, d]
        a : constant term
        b : constant scale
        c : length scale
        d : noise term
        notice that kernel parameters are exponentiated, take np.log(theta) in
        advance
    optimize: bool
        if True activates the kernel parameter optimizer
    relabel_nodes: bool
        if True the nodes are relabelled to consecutive integers
        
    Methods
    ----------
    calc_shortest_paths():
        calculates the shortest path matrix using Dijkstra's algorithm
    pivot_distance(pivot=0)
        returns pivot distance list respect to pivot
    random_assign_nodes():
        assigns nodes to training and test randomly, uses GPnet.seed
    kernel(nodes_a, nodes_b, theta, measnoise=1.0, wantderiv=True)
        calculates covariance matrix between nodes_a and nodes_b with
        theta parameters
    is_pos_def(test_mat):
        returns True if test_mat is positive definite
    logp()
        returns LogMarginalLikelihood
    plot_graph(filename=False):
        plots Graph with training/test/other labels
        if filename is defined saves plot as filename.png
    plot_prior():
        plots 5 extractions from prior process distribution
        if filename is defined saves plot as filename.png
    plot_post():
        plots 5 extractions from posterior process distribution
        if filename is defined saves plot as filename.png
    """

    def __init__(
        self,
        Graph,
        totnodes,
        ntrain,
        ntest,
        deg,
        seed,
        training_nodes,
        training_values,
        test_nodes,
        theta,
        optimize,
        relabel_nodes,
        ):
        self.N = ntrain
        self.n = ntest
        self.deg = deg
        self.seed = seed

        self.is_trained = False
        self.optimize = optimize

        self.theta = theta
        
        self.relabel_nodes = relabel_nodes

        if totnodes == False:
            self.totnodes = self.N + self.n
        else:
            self.totnodes = totnodes

        if Graph == False:
            print("> Initializing Random Regular Graph")
            print(self.totnodes, "nodes")
            print("node degree", self.deg)
            G = nx.random_regular_graph(deg, totnodes)

        else:
            G = Graph
            self.totnodes = len(Graph.nodes)
            
        self.Graph = Graph
        
        self.orig_labels_dict = dict(zip(G, range(len(G.nodes))))
        self.orig_labels_invdict = dict([[v,k] for k,v in self.orig_labels_dict.items()])
        
        if relabel_nodes == True :
            print('> Relabeling nodes, orig. names stored in self.orig_labels_dict')
            self.Graph = nx.relabel_nodes(G, self.orig_labels_dict)

        self.training_nodes = training_nodes
        self.test_nodes = test_nodes
        # self.other_nodes = other_nodes

        if training_nodes == False or test_nodes == False:
            print("> Assigning Nodes Randomly ( seed =", self.seed, ")")
            print(self.N, " training nodes")
            print(self.n, " test nodes")
            print((self.totnodes - (self.N + self.n)), " idle nodes")

            self.random_assign_nodes()

        self.calc_shortest_paths()

        # init plot stuff
        self.plot_pos = nx.kamada_kawai_layout(self.Graph)

        # END INIT #

    def pivot_distance(self, pivot=0):
        pivot_distance = pd.Series(
            dict(nx.single_source_shortest_path_length(self.Graph, pivot))
        ).sort_index()
        return pivot_distance

    def calc_shortest_paths(self):
        # shortest_paths_lengths = dict(nx.all_pairs_shortest_path_length(G))
        shortest_paths_lengths = dict(nx.all_pairs_shortest_path_length(self.Graph))
        self.dist = pd.DataFrame(shortest_paths_lengths).sort_index(axis=1)
        return

    def random_assign_nodes(self):

        if self.N + self.n > self.totnodes:
            raise ValueError(
                "tot. nodes cannot be less than training nodes + test nodes"
            )
        # training_nodes = list(G.nodes)[0:N]
        random.seed(self.seed)
        self.training_nodes = random.sample(list(self.Graph.nodes), self.N)
        self.training_nodes.sort()

        # test_nodes = list(G.nodes)[N:N+n]
        self.test_nodes = random.sample(
            (set(self.Graph.nodes) - set(self.training_nodes)), self.n
        )
        self.test_nodes.sort()

        self.other_nodes = (
            set(self.Graph.nodes) - set(self.training_nodes) - set(self.test_nodes)
        )
        self.other_nodes = list(self.other_nodes)
        self.other_nodes.sort()
        return self

    def is_pos_def(self, test_mat):
        return np.all(np.linalg.eigvals(test_mat) > 0)
    
    def optimize_params(self, gtol=1e-3, maxiter=200, disp=1):
        if self.optimize != False:
            print("> Optimizing parameters")
            print("method used: ", self.optimize["method"])
            print("bounds: ", self.optimize["bounds"])
            res = so.minimize(
                fun=self.logPosterior,
                x0=self.theta,
                args=(self.training_nodes, self.t),
                method=self.optimize["method"],
                bounds=self.optimize["bounds"],
                options={"disp": True},
            )
            self.theta = res["x"]
            print("new parameters: ", self.theta)
        return self


#    def kernel(self, nodes_a, nodes_b, theta, measnoise=1.0, wantderiv=True):
#        """
#        Kernel Function
#        ---------------
#        
#        k(nodes_a, nodes_b) = exp(a) + exp(b) * exp(-1/2 * (dist/exp(c))^2) + I*d
#        
#        with theta=[a,b,c,d]
#        
#        
#        Parameters
#        ----------
#        
#        nodes_a, nodes_b : list
#            list of nodes between which the correlation matrix is calculated
#        theta: 
#            parameters, described aboce
#        measnoise: 
#            scale for measured noise ( just testing purposes )
#        wantderiv:
#            if True returns a k[len(nodes_a), len(nodes_b), len(theta) +1] ndarray
#            k[:,:,0] is the covariance matrix
#            K[:,:,j] are the the j-th partial derivatives respect to parameters
#        """
#        theta = np.squeeze(theta)
#        theta = np.exp(theta)
#        # graph_distance_matrix = shortest_path_graph_distances(Graph)
#        nodelist = list(self.Graph.nodes)
#        nodeset = set(nodes_a).union(set(nodes_b))
#        nodes_to_drop = [x for x in nodelist if x not in nodeset]
#        cols_to_drop = set(nodes_to_drop).union(set(nodes_b) - set(nodes_a))
#        rows_to_drop = set(nodes_to_drop).union(set(nodes_a) - set(nodes_b))
#
#        d1 = len(nodes_a)
#        d2 = len(nodes_b)
#
#        p = self.dist.drop(cols_to_drop).drop(rows_to_drop, 1)
#
#        if isinstance(theta[0], np.ndarray):
#            p_dim = np.tile(p.values, (len(theta), 1, 1))
#            theta_dim = np.tile(theta, (d2, d1, 1, 1)).T
#
#        else:
#            p_dim = p.values
#            theta_dim = theta
#
#        d_squared = (p_dim / theta_dim[2]) ** 2
#
#        exp1 = np.exp(-0.5 * d_squared)
#
#        # k = theta_dim[0] + theta_dim[1] * exp1
#        k = (
#            theta_dim[0]
#            + theta_dim[1] * exp1
#            + measnoise * theta_dim[3] * np.eye(d1, d2)
#        )
#
#        if wantderiv:
#            K = np.zeros((d1, d2, len(theta) + 1))
#            # K[:,:,0] is the original covariance matrix
#            K[:, :, 0] = k + measnoise * theta[2] * np.eye(d1, d2)
#            K[:, :, 1] = theta_dim[0]
#            K[:, :, 2] = theta_dim[1] * exp1
#            K[:, :, 3] = theta_dim[1] * exp1 * d_squared
#            K[:, :, 4] = theta_dim[3] * np.eye(d1, d2)
#            return K
#        else:
#            #            return k + measnoise * theta_dim[2] * np.eye(d1, d2)
#            return k


    def kernel(self, nodes_a, nodes_b, theta, measnoise=1.0, wantderiv=True):
        """
        Kernel Function
        ---------------
        
        k(nodes_a, nodes_b) = exp(a) + exp(b) * exp(-1/2 * (dist/exp(c))^2) + I*d
        
        with theta=[a,b,c,d]
        
        
        Parameters
        ----------
        
        nodes_a, nodes_b : list
            list of nodes between which the correlation matrix is calculated
        theta: 
            parameters, described aboce
        measnoise: 
            scale for measured noise ( just testing purposes )
        wantderiv:
            if True returns a k[len(nodes_a), len(nodes_b), len(theta) +1] ndarray
            k[:,:,0] is the covariance matrix
            K[:,:,j] are the the j-th partial derivatives respect to parameters
        """
        if not len(theta) == 1:
            theta = np.squeeze(theta)
            
        theta = np.exp(theta)
        # graph_distance_matrix = shortest_path_graph_distances(Graph)
        nodelist = list(self.Graph.nodes)
        nodeset = set(nodes_a).union(set(nodes_b))
        nodes_to_drop = [x for x in nodelist if x not in nodeset]
        cols_to_dropset = set(nodes_to_drop).union(set(nodes_b) - set(nodes_a))
        rows_to_dropset = set(nodes_to_drop).union(set(nodes_a) - set(nodes_b))
        
        if self.relabel_nodes == False:
            cols_to_drop = [self.orig_labels_dict[idx] for idx in cols_to_dropset]
            rows_to_drop = [self.orig_labels_dict[idx] for idx in rows_to_dropset]
        else:
            cols_to_drop = list(cols_to_dropset)
            rows_to_drop = list(rows_to_dropset)
            
        
        # need to keep track of node names somehow
        d1 = len(nodes_a)
        d2 = len(nodes_b)
        
        
        Lnorm = ss.csc_matrix(nx.normalized_laplacian_matrix(self.Graph))
        assert theta[0] < 1, "Lambda must be < 1" % theta[0]
        K = sl.expm(theta[0] * Lnorm).toarray()
        
        k = np.delete(K, cols_to_drop, axis=0)
        k = np.delete(k, rows_to_drop, axis=1)
        
        k = k + measnoise*theta[1]
        
        return k
        
        
    @abstractmethod
    def logPosterior(self, theta, *args):
        raise NotImplementedError(
            "logPosterior() must be overridden by GPnetRegressor or GPnetClassifier"
        )

    def logp(self):
        return -self.logPosterior(self.theta, self.training_nodes, self.t)

    def plot_graph(self, filename=False):
        pl.figure(figsize=[15, 9])
        pl.title("Graph")
        # node positions
        # draw nodes
        nx.draw_networkx_nodes(
            self.Graph,
            self.plot_pos,
            with_labels=True,
            node_size=200,
            nodelist=self.training_nodes,
            node_color="r",
        )
        nx.draw_networkx_nodes(
            self.Graph,
            self.plot_pos,
            with_labels=True,
            node_size=200,
            nodelist=self.test_nodes,
            node_color="g",
        )
        nx.draw_networkx_nodes(
            self.Graph,
            self.plot_pos,
            with_labels=True,
            node_size=200,
            nodelist=self.other_nodes,
            node_color="b",
        )
        # draw edges
        ec = nx.draw_networkx_edges(self.Graph, self.plot_pos, alpha=0.2)
        # legend
        if self.relabel_nodes == True:
            labels = nx.draw_networkx_labels(self.Graph,labels=self.orig_labels_invdict, pos=self.plot_pos, font_color="k")
        else:
            labels = nx.draw_networkx_labels(self.Graph, pos=self.plot_pos, font_color="k")
        # legend
        training_patch = red_circle
        training_patch._label = "training nodes"
        test_patch = green_circle
        test_patch._label = "test nodes"
        other_patch = blue_circle
        other_patch._label = "other nodes"

        pl.legend(handles=[training_patch, test_patch, other_patch])

        if type(filename) is str:
            pl.savefig(filename, bbox_inches="tight")
        return self

    def plot_prior(self, filename=False):
        L2 = np.linalg.cholesky(self.kstarstar + 1e-6 * np.eye(self.n))
        # f_prior = mu L*N(0,1)
        f_prior = np.dot(L2, np.random.normal(size=(self.n, 5)))
        pl.figure()
        pl.clf()
        pl.plot(self.test_nodes, f_prior)
        pl.title("5 estrazioni dalla dist. a priori")
        pl.xlabel("nodes")
        pl.ylabel("values")
        # pl.axis([-5, 5, -3, 3])
        if type(filename) is str:
            pl.savefig(filename, bbox_inches="tight")

    def plot_post(self, filename=False):
        Lk = np.linalg.solve(self.L, self.kstar.T)
        L2 = np.linalg.cholesky(
            self.kstarstar + 1e-6 * np.eye(self.n) - np.dot(Lk.T, Lk)
        )

        # f_post = mu + L*N(0,1)
        f_post = self.fstar.reshape(-1, 1) + np.dot(
            L2, np.random.normal(size=(self.n, 5))
        )
        pl.figure()
        pl.clf()
        pl.plot(self.test_nodes, f_post)
        pl.title("5 estrazioni dalla dist. a posteriori")
        pl.xlabel("nodes")
        pl.ylabel("values")
        # pl.axis([-5, 5, -3, 3])
        if type(filename) is str:
            pl.savefig(filename, bbox_inches="tight")

    def int_to_list(nodes):
        if type(nodes) == int:
            return [nodes]
        else:
            return nodes

    def plot_lml_landscape(self, plots, params, filename=False):
        pl.rcParams.update({'font.size': 5})
        plcols = 3
        #        if len(plots)%plcols != 0:
        #            plrows = len(plots)//plcols +1
        #        else:
        #            plrows = len(plots)//plcols
        plrows = len(plots) // plcols
        print(plrows, " - ", plcols, "<")

        fig, ax = pl.subplots(plrows, plcols, dpi=300)
        fig.suptitle("LML landscapes", size = 10)
        fig.subplots_adjust(wspace = 0.3, hspace = 0.4)
        for index, item in enumerate(plots):
            #print("Index: ", index)
            plot = plots[item]
            lml = self.lml_landscape(params, plot[0], plot[1], plot[2])
            idx1 = index // plcols
            idx2 = index % plcols
            if plrows == 1:
                idx = idx2
            else:
                idx = (idx1, idx2)
                
                
            #print(idx1, " - ", idx2)
            if len(plot) == 4:
                cax = ax[idx].pcolor(plot[2], plot[1], lml)
            ax[idx].plot(
                [plot[3][0]], [plot[3][1]], marker="o", markersize=5, color="red"
            )
            ax[idx].set(
                xlabel="theta" + str(plot[0][0]), ylabel="theta" + str(plot[0][1]), title = item
            )
            #ax[idx1, idx2].set_title(item)
            fig.colorbar(cax, ax=ax[idx])
            
                
    def lml_landscape(self, theta, axidx, ax1, ax2):

        lml = np.zeros([len(ax1), len(ax2)])
        start = time.time()
        for i in range(len(ax1)):
            for j in range(len(ax2)):
                params = theta
                params[axidx[0]] = ax1[i]
                params[axidx[1]] = ax2[j]
                # print(axidx[0], axidx[1])

                lml[i, j] = -self.logPosterior(params, self.training_nodes, self.t)

        stop = time.time()
        
        print("elapsed time: ", stop-start)
        return lml


class GPnetRegressor(GPnet):
    """
    Class for Regressors
    
    
    Methods
    ---------
    
    predict():
        calculates predictions using training labels
    predict_RW():
        same thing, just implemented differently (to be removed)
    logPosterior(theta, data, labels):
        returns -log marginal likelihood
    gradlogposterior(theta, data, labels):
        returns - gradient(logposterior)
    optimize_params():
        optimizer
    plot_predict_2d(filename=False):
        plots post Gaussian Process in 2d fashion, with node number on x
        if filename is specified saves plot to 'filename.png'
    plot_predict_graph(filename=False):
        plots graph, node's color is proportional to process prediction
        if filename is specified saves plot to 'filename.png'
    set_training_values(training_values):
        set training values to training_values
        
    """

    def __init__(
        self,
        Graph=False,
        totnodes=False,
        ntrain=100,
        ntest=90,
        deg=4,
        seed=0,
        training_nodes=False,
        training_values=False,
        test_nodes=False,
        theta=[0.1, 0.1, 0.1],
        optimize=False,
        relabel_nodes = False,):

        super(GPnetRegressor, self).__init__(
            Graph,
            totnodes,
            ntrain,
            ntest,
            deg,
            seed,
            training_nodes,
            training_values,
            test_nodes,
            theta,
            optimize,
            relabel_nodes,
        )
        self.pivot_flag = False
        if training_values == False:
            self.pivot_flag = True
            self.pvtdist = self.pivot_distance(list(self.Graph.nodes)[0])
            self.t = self.pvtdist[self.training_nodes]
        else:
            self.t = training_values

    def set_training_values(self, training_values):
        self.t = training_values

    def oldpredict(self):
        self.optimize_params()

        self.k_not_posdef_flag = False
        self.kstar_not_posdef_flag = False
        # self.fstar_t = np.mean(self.t)
        self.k = self.kernel(
            nodes_a=self.training_nodes,
            nodes_b=self.training_nodes,
            theta=self.theta,
            wantderiv=False,
        )

        self.kstar = self.kernel(
            nodes_a=self.test_nodes,
            nodes_b=self.training_nodes,
            theta=self.theta,
            wantderiv=False,
            measnoise=False,
        )
        self.kstarstar = self.kernel(
            nodes_a=self.test_nodes,
            nodes_b=self.test_nodes,
            theta=self.theta,
            wantderiv=False,
        )

        self.kstarstar_diag = np.diag(self.kstarstar)

        if not self.is_pos_def(self.k):
            self.k_not_posdef_flag = True
            # raise ValueError("K is not positive definite")
            print("K not positive definite, aborting...")
            return self
        if not self.is_pos_def(self.kstarstar):
            self.kstar_not_posdef_flag = True
            # raise ValueError("K** is not positive definite")
            print("K** not positive definite, aborting...")
            return self

        self.L = np.linalg.cholesky(self.k)
        invk = np.linalg.solve(
            self.L.transpose(),
            np.linalg.solve(self.L, np.eye(len(self.training_nodes))),
        )
        self.fstar = np.squeeze(np.dot(self.kstar, np.dot(invk, self.t)))
        self.var = self.kstarstar_diag - np.diag(
            np.dot(self.kstar, np.dot(invk, self.kstar.T))
        )
        self.var = np.squeeze(np.reshape(self.var, (self.n, 1)))
        self.s = np.sqrt(self.var)

        print("succesfully trained model")
        self.is_trained = True

        return (self.fstar, self.s)

    def calc_ktot(self):
        self.ktot = self.kernel(
            nodes_a=self.Graph.nodes,
            nodes_b=self.Graph.nodes,
            theta=self.theta,
            wantderiv=False,
        )

    def predict(self):
        # predicts the same exact results as GPnetRegressor.predict(), just reimplemented using Algorithm 2.1 in Rasmussen to make sure it was not the problem
        self.optimize_params()

        self.k_not_posdef_flag = False
        self.kstar_not_posdef_flag = False
        
        self.t_mean = np.mean(self.t)
        self.t_shifted = self.t - self.t_mean
        
        self.k = self.kernel(
            nodes_a=self.training_nodes,
            nodes_b=self.training_nodes,
            theta=self.theta,
            wantderiv=False,
        )

        self.kstar = self.kernel(
            nodes_a=self.test_nodes,
            nodes_b=self.training_nodes,
            theta=self.theta,
            wantderiv=False,
            measnoise=False,
        )
        self.kstarstar = self.kernel(
            nodes_a=self.test_nodes,
            nodes_b=self.test_nodes,
            theta=self.theta,
            wantderiv=False,
        )

        self.kstarstar_diag = np.diag(self.kstarstar)

        if not self.is_pos_def(self.k):
            self.k_not_posdef_flag = True
            # raise ValueError("K is not positive definite")
            print("K not positive definite, aborting...")
            return self
        if not self.is_pos_def(self.kstarstar):
            self.kstar_not_posdef_flag = True
            # raise ValueError("K** is not positive definite")
            print("K** not positive definite, aborting...")
            return self

        self.L = np.linalg.cholesky(self.k)
        self.alpha = np.linalg.solve(self.L.T, np.linalg.solve(self.L, self.t_shifted))
        self.fstar = np.dot(self.kstar, self.alpha) + self.t_mean
        self.v = np.linalg.solve(self.L, self.kstar.T)
        self.V = self.kstarstar_diag - np.dot(self.v.T, self.v)
        self.s = np.sqrt(np.diag(self.V))
        print("succesfully trained model")
        self.is_trained = True

        return (self.fstar, self.V.diagonal())

    def oldlogPosterior(self, theta, *args):
        data, t = args
        k = self.kernel(data, data, theta, wantderiv=False)
        if self.is_pos_def(k) == False:
            return +999
        L = np.linalg.cholesky(k)
        beta = np.linalg.solve(L.transpose(), np.linalg.solve(L, t))
        logp = (
            -0.5 * np.dot(t.transpose(), beta)
            - np.sum(np.log(np.diag(L)))
            - np.shape(data)[0] / 2.0 * np.log(2 * np.pi)
        )
        return -logp

    def logPosterior(self, theta, *args):
        data, t = args

        K = self.kernel(data, data, theta, wantderiv=False)
        try:
            L = np.linalg.cholesky(K)
        except np.linalg.LinAlgError:
            return -np.inf
        alpha = np.linalg.solve(L.T, np.linalg.solve(L, t))
        logp = (
            -0.5 * np.dot(t.T, alpha)
            - np.sum(np.log(np.diag(L)))
            - K.shape[0] * 0.5 * np.log(2 * np.pi)
        )
        return -logp

    def oldlogPosterior(self, theta, *args):
        data, t = args
        t1 = t.copy()
        t1v = t1.values
        d1 = len(data)
        theta = np.squeeze(theta)
        if isinstance(theta[0], np.ndarray):
            #            print("hey")
            #            p_dim = np.tile(p.values, (len(theta[0]),1,1))
            theta_dim = np.tile(theta, (d1, d1, 1, 1)).T
            t1v = np.tile(t1v, (len(theta_dim[0]), 1))
        else:
            theta_dim = theta
        k = self.kernel(data, data, theta, wantderiv=False)
        try:
            L = np.linalg.cholesky(k)  # Line 2
        except np.linalg.LinAlgError:
            if isinstance(theta[0], np.ndarray):
                return np.full(len(theta[0]), -np.inf)
            else:
                return -np.inf
        # return (-np.inf, np.zeros_like(theta)) if eval_gradient else -np.inf

        # L = np.linalg.cholesky(k)

        if isinstance(theta[0], np.ndarray):

            alpha = np.linalg.solve(L, t1v)
            # alpha.resize(len(alpha), 1)
            #            t1v.resize(len(t1), 1)
            log_likelihood_dims = -0.5 * np.diag(t1v * alpha)
            #            log_likelihood_dims = -0.5 * np.einsum("ik,ik->k", t1v, alpha)
            log_likelihood_dims -= np.log(np.diagonal(L, axis1=1, axis2=2)).sum(axis=1)
            log_likelihood_dims -= np.squeeze(
                np.tile(k.shape[1], (1, len(theta))) / 2 * np.log(2 * np.pi)
            )
            logp = log_likelihood_dims  # sum over dimensions
            # beta = np.linalg.solve(L.transpose(), np.linalg.solve(L,t))
            # logp = -0.5*np.dot(t.transpose(),beta) - np.sum(np.log(np.diag(L))) - np.shape(data)[0] /2. * np.log(2*np.pi)
            # print("logp is ",-logp)
        else:
            alpha = np.linalg.solve(L, t)
            alpha.resize(len(alpha), 1)
            t1v.resize(len(t1), 1)
            log_likelihood_dims = -0.5 * np.einsum("ik,ik->k", t1v, alpha)
            log_likelihood_dims = -0.5 * np.trace(t1v * alpha)
            log_likelihood_dims -= np.log(np.diag(L)).sum()
            log_likelihood_dims -= k.shape[0] / 2 * np.log(2 * np.pi)
            logp = log_likelihood_dims.sum(-1)  # sum over dimensions
            # beta = np.linalg.solve(L.transpose(), np.linalg.solve(L,t))
            # logp = -0.5*np.dot(t.transpose(),beta) - np.sum(np.log(np.diag(L))) - np.shape(data)[0] /2. * np.log(2*np.pi)
            # print("logp is ",-logp)

        return -logp

    def oldgradLogPosterior(self, theta, *args):
        data, t = args
        theta = np.squeeze(theta)
        d = len(theta)
        # K = kernel(data,data,theta,wantderiv=True)
        K = self.kernel(data, data, theta, wantderiv=True)

        L = np.linalg.cholesky(np.squeeze(K[:, :, 0]))
        invk = np.linalg.solve(
            L.transpose(), np.linalg.solve(L, np.eye(np.shape(data)[0]))
        )

        dlogpdtheta = np.zeros(d)
        for d in range(1, len(theta) + 1):
            dlogpdtheta[d - 1] = 0.5 * np.dot(
                t.transpose(),
                np.dot(invk, np.dot(np.squeeze(K[:, :, d]), np.dot(invk, t))),
            ) - 0.5 * np.trace(np.dot(invk, np.squeeze(K[:, :, d])))

        return -dlogpdtheta

    def gradLogPosterior(self, theta, *args):
        data, t = args
        theta = np.squeeze(theta)
        k = self.kernel(data, data, theta, wantderiv=True)
        try:
            L = np.linalg.cholesky(k[:, :, 0])  # Line 2
            K_inv = np.dot(np.linalg.inv(L).T, np.linalg.inv(L))
        except np.linalg.LinAlgError:
            return -np.inf
        # return (-np.inf, np.zeros_like(theta)) if eval_gradient else -np.inf

        # L = np.linalg.cholesky(k)
        alpha = np.linalg.solve(L, t)

        tmp = np.eye(k.shape[0]) * np.dot(alpha, alpha.T)
        # tmp = np.einsum("ik,jk->ijk", alpha, alpha)  # k: output-dimension
        # tmp2 = np.linalg.solve(L, np.eye(k.shape[0]))[:, :, np.newaxis]
        tmp -= K_inv
        # Compute "0.5 * trace(tmp.dot(K_gradient))" without
        # constructing the full matrix tmp.dot(K_gradient) since only
        # its diagonal is required
        log_likelihood_gradient_dim = np.zeros([len(data), len(data), len(theta)])
        for i in range(0, len(theta)):
            log_likelihood_gradient_dim[:, :, i] = 0.5 * np.dot(tmp, k[:, :, i + 1])
            log_likelihood_gradient = np.trace(log_likelihood_gradient_dim, axis1=0)

        # log_likelihood_gradient_dims = 0.5 * np.einsum("ij,ijk->ijk", tmp, k[:, :, 1:])
        # log_likelihood_gradient = log_likelihood_gradient_dims.sum(-1)
        print(log_likelihood_gradient)
        return -log_likelihood_gradient
    #            self.theta = so.fmin_cg(
    #                self.logPosterior,
    #                self.theta,
    #                fprime=self.gradLogPosterior,
    #                args=(self.training_nodes, self.t),
    #                gtol=gtol,
    #                maxiter=200,
    #                disp=1,
    #            )

    def gen_cmap(self):
        self.vmin = min(self.t.min(), self.fstar.min())
        self.vmax = max(self.t.max(), self.fstar.max())
        self.cmap = pl.cm.inferno_r

    def plot_predict_2d(self, filename=False):
        pl.figure(figsize=[15, 9])
        pl.clf()
        pl.plot(self.training_nodes, self.t, "r+", ms=20)
        if self.pivot_flag == True:
            pl.plot(self.pvtdist)

        pl.gca().fill_between(
            self.test_nodes, self.fstar - self.s, self.fstar + self.s, color="#dddddd"
        )
        pl.plot(self.test_nodes, self.fstar, "ro", ms=4)
        pl.plot(self.test_nodes, self.fstar, "r--", lw=2)
        pl.title("Gaussian Process Mean and Variance")
        loglikelihood = -self.logPosterior(self.theta, self.training_nodes, self.t)
#        pl.title(
#            "Valore medio e margini a posteriori\n(length scale: %.3f , constant scale: %.3f , noise variance: %.3f )\n Log-Likelihood: %.3f"
#            % (self.theta[1], self.theta[0], self.theta[2], loglikelihood)
#        )
        pl.title(
                "Valore medio e margini a posteriori\n(lambda: %.3f)"%(self.theta[0])
        )
        pl.xlabel("nodes")
        pl.ylabel("values")
        if type(filename) is str:
            pl.savefig(filename, bbox_inches="tight")
        # pl.axis([-5, 5, -3, 3])
        return self

    def plot_predict_graph(self, filename=False):

        if self.is_trained == False:
            print("need to train a model first, use GPnetRegressor.predict()")
            return

        pl.figure(figsize=[15, 9])
        pl.title("Prediction plot")

        self.gen_cmap()
        nx.draw_networkx_nodes(
            self.Graph,
            self.plot_pos,
            nodelist=self.training_nodes,
            node_color=np.squeeze(self.t[(self.training_nodes)]),
            with_labels=True,
            node_size=200,
            cmap=self.cmap,
            node_shape="v",
        )

        nx.draw_networkx_nodes(
            self.Graph,
            self.plot_pos,
            nodelist=self.other_nodes,
            node_color="gray",
            with_labels=True,
            node_size=200,
            cmap=self.cmap,
        )

        nx.draw_networkx_nodes(
            self.Graph,
            self.plot_pos,
            nodelist=self.test_nodes,
            node_color=self.fstar,
            with_labels=True,
            node_size=200,
            cmap=self.cmap,
            node_shape="s",
        )

        ec = nx.draw_networkx_edges(self.Graph, self.plot_pos, alpha=0.2)

        sm = pl.cm.ScalarMappable(
            cmap=self.cmap, norm=pl.Normalize(vmin=self.vmin, vmax=self.vmax)
        )
        sm.set_array([])
        cbar = pl.colorbar(sm)

        labels = nx.draw_networkx_labels(self.Graph, pos=self.plot_pos, font_color="k")

        # legend
        training_patch = red_triangle
        training_patch._label = "training nodes"
        test_patch = green_square
        test_patch._label = "test nodes"
        other_patch = gray_circle
        other_patch._label = "other nodes"

        pl.legend(handles=[training_patch, test_patch, other_patch])

        if type(filename) is str:
            pl.savefig(filename, bbox_inches="tight")
        return self


class GPnetClassifier(GPnet):
    """
    Class for Classifiers
    
    
    Methods
    ---------
    predict():
        calculates predictions using training labels
    NRiteration(data, targets, theta, tol=0.1, phif=1e100, scale=1.):
        finds maximum f_star mode for Laplace Approximation
    logPosterior(theta, data, labels):
        returns -log marginal likelihood
    gradlogposterior(theta, data, labels):
        returns - gradient(logposterior)
    plot_latent(filename=False):
        plots latent Gaussian Process in 2d fashion, with node number on x
        if filename is specified saves plot to 'filename.png'
    plot_predict_graph(filename=False):
        plots graph, node's color is proportional to process prediction
        if filename is specified saves plot to 'filename.png'
    """

    def __init__(
        self,
        Graph=False,
        totnodes=False,
        ntrain=100,
        ntest=90,
        deg=4,
        seed=0,
        training_nodes=False,
        training_values=False,
        test_nodes=False,
        theta=[0.1, 0.1, 0.1],
        optimize=False,
        relabel_nodes=False,
    ):

        super(GPnetClassifier, self).__init__(
            Graph,
            totnodes,
            ntrain,
            ntest,
            deg,
            seed,
            training_nodes,
            training_values,
            test_nodes,
            theta,
            optimize,
            relabel_nodes,
        )

        self.pivot_flag = False

        if training_values == False:
            print("no training labels where specified")
            print(
                "> Setting labels to (np.sin(0.6 * self.pvtdist) > 0).replace({True: 1, False: -1})"
            )
            self.pivot_flag = True
            self.pvtdist = self.pivot_distance(0)
            self.t = self.pvtdist[self.training_nodes]
            self.binary_labels = (np.sin(0.6 * self.pvtdist) > 0).replace(
                {True: 1, False: -1}
            )
            self.training_labels = self.binary_labels[self.training_nodes]

        else:
            self.training_labels = training_values

    def logPosterior(self, theta, *args):
        data, targets = args
        (f, logq, a) = self.NRiteration(data, targets, theta)
        return -logq

    def NRiteration_old(self, data, targets, theta, tol=0.1, phif=1e100, scale=1.0):
        # print("iteration")
        # pag 46 RASMUSSEN-WILLIAMS
        K = self.kernel(data, data, theta, wantderiv=False)
        # K = kernel(data,data,theta,wantderiv=False)
        n = np.shape(targets)[0]
        f = np.zeros((n, 1))
        #        tol = 0.1
        #        phif = 1e100
        #        scale = 1.
        count = 0
        targets = targets.values.reshape(n, 1)
        while True:

            count += 1
            s = np.where(f < 0, f, 0)
            W = np.diag(
                np.squeeze(np.exp(2 * s - f) / ((np.exp(s) + np.exp(s - f)) ** 2))
            )
            sqrtW = np.sqrt(W)
            # L = cholesky(B)
            L = np.linalg.cholesky(np.eye(n) + np.dot(sqrtW, np.dot(K, sqrtW)))
            p = np.exp(s) / (np.exp(s) + np.exp(s - f))
            b = np.dot(W, f) + 0.5 * (targets + 1) - p
            a = scale * (
                b
                - np.dot(
                    sqrtW,
                    np.linalg.solve(
                        L.transpose(), np.linalg.solve(L, np.dot(sqrtW, np.dot(K, b)))
                    ),
                )
            )
            f = np.dot(K, a)
            oldphif = phif
            phif = (
                np.log(p)
                - 0.5 * np.dot(f.transpose(), np.dot(np.linalg.inv(K), f))
                - 0.5 * np.sum(np.log(np.diag(L)))
                - np.shape(data)[0] / 2.0 * np.log(2 * np.pi)
            )
            # print(phif)
            # print("loop",np.sum((oldphif-phif)**2))
            if np.sum((oldphif - phif) ** 2) < tol:
                break
            elif count > 100:
                count = 0
                scale = scale / 2.0

        s = -targets * f
        ps = np.where(s > 0, s, 0)
        # logq = -0.5*np.dot(a.transpose(),f) -np.sum(np.log(ps+np.log(np.exp(-ps) + np.exp(s-ps)))) - np.trace(np.log(L))
        logq = (
            -0.5 * np.dot(a.transpose(), f)
            - np.sum(np.log(ps + np.log(np.exp(-ps) + np.exp(s - ps))))
            - sum(np.log(L.diagonal()))
        )
        return (f, logq, a)

    def NRiteration(self, data, targets, theta, tol=0.1, phif=1e100, scale=1.0):
        # print("iteration")
        # pag 46 RASMUSSEN-WILLIAMS
        K = self.kernel(data, data, theta, wantderiv=False)
        # K = kernel(data,data,theta,wantderiv=False)
        n = np.shape(targets)[0]
        f = np.zeros((n, 1))
        #        tol = 0.1
        #        phif = 1e100
        #        scale = 1.
        count = 0
        targets = targets.values.reshape(n, 1)
        while True:

            count += 1
            # s = np.where(f < 0, f, 0)
            W = np.diag(np.squeeze(np.exp(-f) / (1 + np.exp(-f)) ** 2))

            sqrtW = np.sqrt(W)
            # L = cholesky(B)
            L = np.linalg.cholesky(np.eye(n) + np.dot(sqrtW, np.dot(K, sqrtW)))
            p = 1 / (1 + np.exp(-f))
            b = np.dot(W, f) + 0.5 * (targets + 1) - p
            a = scale * (
                b
                - np.dot(
                    sqrtW,
                    np.linalg.solve(
                        L.transpose(), np.linalg.solve(L, np.dot(sqrtW, np.dot(K, b)))
                    ),
                )
            )
            f = np.dot(K, a)
            oldphif = phif
            phif = (
                np.log(p)
                - 0.5 * np.dot(f.transpose(), np.dot(np.linalg.inv(K), f))
                - 0.5 * np.sum(np.log(np.diag(L)))
                - np.shape(data)[0] / 2.0 * np.log(2 * np.pi)
            )
            # print(phif)
            # print("loop",np.sum((oldphif-phif)**2))
            if np.sum((oldphif - phif) ** 2) < tol:
                break
            elif count > 100:
                count = 0
                scale = scale / 2.0

        s = -targets * f
        # ps = np.where(s > 0, s, 0)
        # logq = -0.5*np.dot(a.transpose(),f) -np.sum(np.log(ps+np.log(np.exp(-ps) + np.exp(s-ps)))) - np.trace(np.log(L))
        logq = (
            -0.5 * np.dot(a.transpose(), f)
            - np.sum(np.log(1 + np.log(1 + np.exp(-s))))
            - sum(np.log(L.diagonal()))
        )

        return (f, logq, a)

    def gradLogPosterior(self, theta, *args):
        data, targets = args
        theta = np.squeeze(theta)
        n = np.shape(targets)[0]
        K = self.kernel(data, data, theta, wantderiv=True)
        # K = kernel(data,data,theta,wantderiv=True)
        (f, logq, a) = self.NRiteration(data, targets, theta)
        s = np.where(f < 0, f, 0)
        W = np.diag(np.squeeze(np.exp(2 * s - f) / ((np.exp(s) + np.exp(s - f)) ** 2)))
        sqrtW = np.sqrt(W)
        L = np.linalg.cholesky(np.eye(n) + np.dot(sqrtW, np.dot(K[:, :, 0], sqrtW)))

        R = np.dot(sqrtW, np.linalg.solve(L.transpose(), np.linalg.solve(L, sqrtW)))
        C = np.linalg.solve(L, np.dot(sqrtW, K[:, :, 0]))
        p = np.exp(s) / (np.exp(s) + np.exp(s - f))
        hess = -np.exp(2 * s - f) / (np.exp(s) + np.exp(s - f)) ** 2
        s2 = -0.5 * np.dot(
            np.diag(np.diag(K[:, :, 0]) - np.diag(np.dot(C.transpose(), C))),
            2 * hess * (0.5 - p),
        )

        targets = targets.values.reshape(n, 1)

        gradZ = np.zeros(len(theta))
        for d in range(1, len(theta) + 1):
            s1 = 0.5 * (np.dot(a.transpose(), np.dot(K[:, :, d], a))) - 0.5 * np.trace(
                np.dot(R, K[:, :, d])
            )
            b = np.dot(K[:, :, d], (targets + 1) * 0.5 - p)
            p = np.exp(s) / (np.exp(s) + np.exp(s - f))
            s3 = b - np.dot(K[:, :, 0], np.dot(R, b))
            gradZ[d - 1] = s1 + np.dot(s2.transpose(), s3)

        return -gradZ

    def predict(self):
        # vedi algoritmo 3.2 Rasmussen
        if self.optimize != False:
            self.optimize_params()
        
        K = self.kernel(
            self.training_nodes, self.training_nodes, self.theta, wantderiv=False
        )
        n = np.shape(self.training_labels)[0]
        kstar = self.kernel(
            self.training_nodes,
            self.test_nodes,
            self.theta,
            wantderiv=False,
            measnoise=0,
        )
        (f, logq, a) = self.NRiteration(
            self.training_nodes, self.training_labels, self.theta
        )
        targets = self.training_labels.values.reshape(n, 1)
        s = np.where(f < 0, f, 0)
        # step 2
        W = np.diag(np.squeeze(np.exp(2 * s - f) / ((np.exp(s) + np.exp(s - f)) ** 2)))
        sqrtW = np.sqrt(W)
        L = np.linalg.cholesky(np.eye(n) + np.dot(sqrtW, np.dot(K, sqrtW)))
        p = np.exp(s) / (np.exp(s) + np.exp(s - f))
        self.fstar = np.squeeze(np.dot(kstar.transpose(), (targets + 1) * 0.5 - p))
        v = np.linalg.solve(L, np.dot(sqrtW, kstar))
        kstarstar = self.kernel(
            self.test_nodes, self.test_nodes, self.theta, wantderiv=False, measnoise=0
        ).diagonal()
        module_v = np.dot(v.transpose(), v)

        self.V = (kstarstar - module_v).diagonal()

        # V = self.kernel(self.test_nodes,self.test_nodes,self.theta,wantderiv=False,measnoise=0).diagonal()-np.dot(v.transpose(),v)

        alpha = np.tile((1 / (2 * self.V)), (5, 1))
        # gamma = LAMBDAS * fstar
        gamma = np.einsum("i,k->ik", LAMBDAS, self.fstar.T)
        lambdas_mat = np.tile(LAMBDAS, (len(self.test_nodes), 1)).T
        Vmat = np.tile(self.V, (5, 1))
        integrals = (
            np.sqrt(np.pi / alpha)
            * erf(gamma * np.sqrt(alpha / (alpha + lambdas_mat ** 2)))
            / (2 * np.sqrt(Vmat * 2 * np.pi))
        )
        pi_star = (COEFS * integrals).sum(axis=0) + 0.5 * COEFS.sum()

        self.predicted_probs = np.vstack((1 - pi_star, pi_star)).T
        self.s = np.sqrt(self.V)

        print("succesfully trained model")
        self.is_trained = True

        return (self.fstar.T, self.V, self.predicted_probs)
        # return (fstar,V)

    def plot_latent(self, filename=False):
        pl.figure()
        pl.clf()
        pl.plot(self.training_nodes, self.training_labels, "r+", ms=20)

        pl.gca().fill_between(
            self.test_nodes, self.fstar - self.s, self.fstar + self.s, color="#dddddd"
        )
        pl.plot(self.test_nodes, self.fstar, "ro", ms=4)
        pl.plot(self.test_nodes, self.fstar, "r--", lw=2)

        loglikelihood = -self.logPosterior(self.theta, self.training_nodes, self.t)
        pl.title(
            "Latent Process Mean and Variance \n(length scale: %.3f , constant scale: %.3f , noise variance: %.3f )\n Log-Likelihood: %.3f"
            % (self.theta[1], self.theta[0], self.theta[2], loglikelihood)
        )
        pl.xlabel("nodes")
        pl.ylabel("values")
        if type(filename) is str:
            pl.savefig(filename, bbox_inches="tight")
        # pl.axis([-5, 5, -3, 3])
        return self

    def plot_predict_graph(self, filename=False):

        if self.is_trained == False:
            print("need to train a model first, use GPnetClassifier.predict()")
            return

        pl.figure(figsize=[15, 9])
        pl.title("Prediction plot")

        self.gen_cmap()
        nx.draw_networkx_nodes(
            self.Graph,
            self.plot_pos,
            nodelist=self.training_nodes,
            node_color=np.where(
                self.training_labels[(self.training_nodes)] > 0,
                self.training_labels[(self.training_nodes)],
                0,
            ),
            with_labels=True,
            node_size=200,
            cmap=self.cmap,
            node_shape="v",
        )

        nx.draw_networkx_nodes(
            self.Graph,
            self.plot_pos,
            nodelist=self.other_nodes,
            node_color="gray",
            with_labels=True,
            node_size=200,
            cmap=self.cmap,
        )

        nx.draw_networkx_nodes(
            self.Graph,
            self.plot_pos,
            nodelist=self.test_nodes,
            node_color=self.predicted_probs.T[0],
            with_labels=True,
            node_size=200,
            cmap=self.cmap,
            node_shape="s",
        )

        ec = nx.draw_networkx_edges(self.Graph, self.plot_pos, alpha=0.2)

        sm = pl.cm.ScalarMappable(cmap=self.cmap, norm=pl.Normalize(vmin=0, vmax=1))
        sm.set_array([])
        cbar = pl.colorbar(sm)

        labels = nx.draw_networkx_labels(self.Graph, pos=self.plot_pos, font_color="k")

        # legend
        training_patch = red_triangle
        training_patch._label = "training nodes"
        test_patch = blue_square
        test_patch._label = "test nodes"
        other_patch = gray_circle
        other_patch._label = "other nodes"

        pl.legend(handles=[training_patch, test_patch, other_patch])

        if type(filename) is str:
            pl.savefig(filename, bbox_inches="tight")
        return self

    def gen_cmap(self):
        self.vmin = 0
        self.vmax = 1
        self.cmap = pl.cm.seismic
