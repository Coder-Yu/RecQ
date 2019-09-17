#coding:utf8
from baseclass.DeepRecommender import DeepRecommender
from baseclass.SocialRecommender import SocialRecommender
from random import choice
import tensorflow as tf
import numpy as np
from math import sqrt
class AGR(SocialRecommender,DeepRecommender):

    def __init__(self,conf,trainingSet=None,testSet=None,relation=None,fold='[1]'):
        DeepRecommender.__init__(self, conf=conf, trainingSet=trainingSet, testSet=testSet, fold=fold)
        SocialRecommender.__init__(self, conf=conf, trainingSet=trainingSet, testSet=testSet, relation=relation,fold=fold)

    def next_batch(self):
        batch_id = 0
        while batch_id < self.train_size:
            if batch_id + self.batch_size <= self.train_size:
                users = [self.data.trainingData[idx][0] for idx in range(batch_id, self.batch_size + batch_id)]
                items = [self.data.trainingData[idx][1] for idx in range(batch_id, self.batch_size + batch_id)]
                batch_id += self.batch_size
            else:
                users = [self.data.trainingData[idx][0] for idx in range(batch_id, self.train_size)]
                items = [self.data.trainingData[idx][1] for idx in range(batch_id, self.train_size)]
                batch_id = self.train_size

            u_idx, i_idx, j_idx = [], [], []
            item_list = self.data.item.keys()
            for i, user in enumerate(users):

                i_idx.append(self.data.item[items[i]])
                u_idx.append(self.data.user[user])

                neg_item = choice(item_list)
                while neg_item in self.data.trainSet_u[user]:
                    neg_item = choice(item_list)
                j_idx.append(self.data.item[neg_item])

            yield u_idx, i_idx, j_idx


    def buildGraph(self):
        #Generator
        with tf.name_scope("generator_social_graph"):





    def initModel(self):
        super(AGR, self).initModel()

        ego_embeddings = tf.concat([self.user_embeddings,self.item_embeddings], axis=0)

        indices = [[self.data.user[item[0]],self.num_users+self.data.item[item[1]]] for item in self.data.trainingData]
        indices += [[self.num_users+self.data.item[item[1]],self.data.user[item[0]]] for item in self.data.trainingData]
        values = [float(item[2])/sqrt(len(self.data.trainSet_u[item[0]]))/sqrt(len(self.data.trainSet_i[item[1]])) for item in self.data.trainingData]*2

        norm_adj = tf.SparseTensor(indices=indices, values=values, dense_shape=[self.num_users+self.num_items,self.num_users+self.num_items])

        self.weights = dict()

        initializer = tf.contrib.layers.xavier_initializer()
        weight_size = [self.embed_size*4,self.embed_size*2,self.embed_size]
        weight_size_list = [self.embed_size] + weight_size

        self.n_layers = 3

        #initialize parameters
        for k in range(self.n_layers):
            self.weights['W_%d_1' % k] = tf.Variable(
                initializer([weight_size_list[k], weight_size_list[k + 1]]), name='W_%d_1' % k)
            self.weights['W_%d_2' % k] = tf.Variable(
                initializer([weight_size_list[k], weight_size_list[k + 1]]), name='W_%d_2' % k)

        all_embeddings = [ego_embeddings]
        for k in range(self.n_layers):
            side_embeddings = tf.sparse_tensor_dense_matmul(norm_adj,ego_embeddings)
            sum_embeddings = tf.matmul(side_embeddings+ego_embeddings, self.weights['W_%d_1' % k])
            bi_embeddings = tf.multiply(ego_embeddings, side_embeddings)
            bi_embeddings = tf.matmul(bi_embeddings, self.weights['W_%d_2' % k])

            ego_embeddings = tf.nn.leaky_relu(sum_embeddings+bi_embeddings)

            # message dropout.
            ego_embeddings = tf.nn.dropout(ego_embeddings, keep_prob=0.9)

            # normalize the distribution of embeddings.
            norm_embeddings = tf.math.l2_normalize(ego_embeddings, axis=1)

            all_embeddings += [norm_embeddings]

        all_embeddings = tf.concat(all_embeddings, 1)
        self.multi_user_embeddings, self.multi_item_embeddings = tf.split(all_embeddings, [self.num_users, self.num_items], 0)

        self.neg_idx = tf.placeholder(tf.int32, name="neg_holder")
        self.neg_item_embedding = tf.nn.embedding_lookup(self.multi_item_embeddings, self.neg_idx)
        self.u_embedding = tf.nn.embedding_lookup(self.multi_user_embeddings, self.u_idx)
        self.v_embedding = tf.nn.embedding_lookup(self.multi_item_embeddings, self.v_idx)

    def buildModel(self):
        init = tf.global_variables_initializer()
        self.sess.run(init)


        y = tf.reduce_sum(tf.multiply(self.u_embedding, self.v_embedding), 1) \
            - tf.reduce_sum(tf.multiply(self.u_embedding, self.neg_item_embedding), 1)

        loss = -tf.reduce_sum(tf.log(tf.sigmoid(y))) + self.regU * (tf.nn.l2_loss(self.u_embedding) +
                                                                    tf.nn.l2_loss(self.v_embedding) +
                                                                    tf.nn.l2_loss(self.neg_item_embedding))
        opt = tf.train.AdamOptimizer(self.lRate)

        train = opt.minimize(loss)

        with tf.Session() as sess:
            init = tf.global_variables_initializer()
            sess.run(init)
            for iteration in range(self.maxIter):
                for n, batch in enumerate(self.next_batch()):
                    user_idx, i_idx, j_idx = batch
                    _, l = sess.run([train, loss],
                                    feed_dict={self.u_idx: user_idx, self.neg_idx: j_idx, self.v_idx: i_idx})
                    print 'training:', iteration + 1, 'batch', n, 'loss:', l
            self.P, self.Q = sess.run([self.multi_user_embeddings, self.multi_item_embeddings])

    def predictForRanking(self, u):
        'invoked to rank all the items for the user'
        if self.data.containsUser(u):
            u = self.data.getUserId(u)
            return self.Q.dot(self.P[u])
        else:
            return [self.data.globalMean] * self.num_items