# -*- coding:utf-8 -*-
# 
# Author: YIN MIAO
# Time: 2018/11/11 14:58
import numpy as np
import tensorflow as tf
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import os
import keras


# leaky ReLu function
def lrelu(x, alpha=0.2):
    return tf.maximum(alpha * x, x)


def xavier_init(size):
    in_dim = size[0]
    stddev = 1. / tf.sqrt(in_dim / 2.)
    return tf.random_normal(shape=size, stddev=stddev)


def he_init(size, stride):
    input_dim = size[2]
    output_dim = size[3]
    filter_size = size[0]

    fan_in = input_dim * filter_size ** 2
    fan_out = output_dim * filter_size ** 2 / (stride ** 2)
    stddev = tf.sqrt(4. / (fan_in + fan_out))
    minval = -stddev * np.sqrt(3)
    maxval = stddev * np.sqrt(3)

    return tf.random_uniform(shape=size, minval=minval, maxval=maxval)


def sample_z(m, n):
    return np.random.uniform(-1., 1., size=[m, n])


class ConvWganGpCifar10(object):

    def __init__(self, batch_size, z_shape,
                 step_num, learning_rate, LAMBDA, DIM):

        self.z_shape = z_shape
        self.batch_size = batch_size
        self.step_num = step_num
        self.learning_rate = learning_rate
        self.DIM = DIM
        self.LAMBDA = LAMBDA

        self.z = tf.placeholder(tf.float32, [None, self.z_shape], name='z')
        self.xv = tf.placeholder(tf.float32, [None, 32, 32, 3], name='xv')
        self.x = tf.reshape(self.xv, [-1, 3072], name='x')

        # Generator
        with tf.variable_scope('Generator'):
            self.G_W1 = tf.Variable(
                xavier_init(size=[self.z_shape, 4 * 4 * 4 * self.DIM]),
                name='mlp_W1'
            )
            self.G_b1 = tf.Variable(
                tf.zeros([4 * 4 * 4 * self.DIM]),
                name='mlp_b1'
            )

            self.G_W2 = tf.Variable(
                he_init([5, 5, 2 * self.DIM, 4 * self.DIM], 2),
                name='deconv_W2'
            )
            self.G_b2 = tf.Variable(
                tf.zeros([2 * self.DIM]),
                name='deconv_b2'
            )
            self.G_W3 = tf.Variable(
                he_init([5, 5, self.DIM, 2 * self.DIM], 2),
                name='deconv_W3'
            )
            self.G_b3 = tf.Variable(
                tf.zeros([self.DIM]),
                name='deconv_b3'
            )
            self.G_W4 = tf.Variable(
                he_init([5, 5, 3, self.DIM], 2),
                name='deconv_W4'
            )
            self.G_b4 = tf.Variable(
                tf.zeros([1]),
                name='deconv_b4'
            )
            self.params_gen = [
                self.G_W1, self.G_b1,
                self.G_W2, self.G_b2,
                self.G_W3, self.G_b3,
                self.G_W4, self.G_b4
            ]

        # Discriminator
        with tf.variable_scope('Discriminator'):
            self.D_W1 = tf.Variable(he_init([5, 5, 3, self.DIM], 2),
                                    name='conv_W1'
                                    )
            self.D_b1 = tf.Variable(tf.zeros([self.DIM]),
                                    name='conv_b1'
                                    )
            self.D_W2 = tf.Variable(he_init([5, 5, self.DIM, 2 * self.DIM], 2),
                                    name='conv_W2'
                                    )
            self.D_b2 = tf.Variable(tf.zeros([2 * self.DIM]),
                                    name='conv_b2'
                                    )
            self.D_W3 = tf.Variable(he_init([5, 5, 2 * self.DIM, 4 * self.DIM], 2),
                                    name='conv_W3'
                                    )
            self.D_b3 = tf.Variable(tf.zeros([4 * self.DIM]),
                                    name='conv_b3'
                                    )
            self.D_W4 = tf.Variable(
                xavier_init([4 * 4 * 4 * self.DIM, 1]),
                name='mlp_W4'
            )
            self.D_b4 = tf.Variable(
                tf.zeros([1]),
                name='mlp_b4'
            )

            self.params_dis = [
                self.D_W1, self.D_b1,
                self.D_W2, self.D_b2,
                self.D_W3, self.D_b3,
                self.D_W4, self.D_b4
            ]
        self.g = self._generator(self.z)
        self.D_real = self._discriminator(self.x)
        self.D_fake = self._discriminator(self.g)
        self.gm = self.downscale(tf.reshape(self.g, (-1, 32, 32, 3)), 2)

        self.loss_dis = -tf.reduce_mean(self.D_real) + tf.reduce_mean(self.D_fake)
        self.loss_gen = -tf.reduce_mean(self.D_fake)

        alpha = tf.random_uniform(
            shape=[self.batch_size, 1],
            minval=0.,
            maxval=1.
        )

        differences = self.g - self.x
        interpolates = self.x + alpha * differences
        gradients = tf.gradients(self._discriminator(interpolates), [interpolates])[0]
        slopes = tf.sqrt(tf.reduce_sum(tf.square(gradients), reduction_indices=[1]))
        gradient_penalty = tf.reduce_mean((slopes - 1.) ** 2)

        self.loss_dis += self.LAMBDA * gradient_penalty

        self.opt_dis = tf.train.AdamOptimizer(
            learning_rate=self.learning_rate,
            beta1=0.5,
            beta2=0.9
        ).minimize(self.loss_dis, var_list=self.params_dis)
        self.opt_gen = tf.train.AdamOptimizer(
            learning_rate=self.learning_rate,
            beta1=0.5,
            beta2=0.9
        ).minimize(self.loss_gen, var_list=self.params_gen)

    def _generator(self, z):
        current_input = z
        current_output = lrelu(tf.add(tf.matmul(current_input, self.G_W1), self.G_b1))
        current_output = tf.reshape(current_output, [-1, 4, 4, 4 * self.DIM])

        current_shape = tf.shape(current_output)
        # shape (4,4,256)
        current_output = lrelu(tf.add(tf.nn.conv2d_transpose(
            value=current_output,
            filter=self.G_W2,
            output_shape=tf.stack(
                [current_shape[0], 2 * current_shape[1], 2 * current_shape[2], 2 * self.DIM]
            ),
            strides=[1, 2, 2, 1],
            padding='SAME'
        ), self.G_b2)
        )
        # shape (8,8,128)
        current_shape = tf.shape(current_output)

        current_output = lrelu(tf.add(tf.nn.conv2d_transpose(
            value=current_output,
            filter=self.G_W3,
            output_shape=tf.stack(
                [current_shape[0], 2 * current_shape[1], 2 * current_shape[2], self.DIM]
            ),
            strides=[1, 2, 2, 1],
            padding='SAME'
        ), self.G_b3)
        )
        # shape (16,16,64)

        current_shape = tf.shape(current_output)
        current_output = tf.nn.sigmoid(tf.add(tf.nn.conv2d_transpose(
            value=current_output,
            filter=self.G_W4,
            output_shape=tf.stack(
                [current_shape[0], 2 * current_shape[1], 2 * current_shape[2], 3]
            ),
            strides=[1, 2, 2, 1],
            padding='SAME'
        ), self.G_b4)
        )
        return tf.reshape(current_output, [-1, 32*32*3])

    def _discriminator(self, x):
        current_input = tf.reshape(x, [-1, 32, 32, 3])

        current_output = lrelu(tf.add(tf.nn.conv2d(
            input=current_input,
            filter=self.D_W1,
            strides=[1, 2, 2, 1],
            padding='SAME'
        ), self.D_b1)
        )

        current_output = lrelu(tf.add(tf.nn.conv2d(
            input=current_output,
            filter=self.D_W2,
            strides=[1, 2, 2, 1],
            padding='SAME'
        ), self.D_b2)
        )

        current_output = lrelu(tf.add(tf.nn.conv2d(
            input=current_output,
            filter=self.D_W3,
            strides=[1, 2, 2, 1],
            padding='SAME'
        ), self.D_b3)
        )

        current_output = tf.reshape(current_output, [-1, 4 * 4 * 4 * self.DIM])
        current_output = tf.add(tf.matmul(current_output, self.D_W4), self.D_b4)

        return current_output

    def downscale(self, x, K):
        mat = np.zeros([K, K, x.get_shape().as_list()[3], x.get_shape().as_list()[3]])
        for i in range(x.get_shape().as_list()[3]):
            mat[:, :, i, i] = 1.0 / K ** 2
        filter = tf.constant(mat, dtype=tf.float32)
        return tf.nn.conv2d(x, filter, strides=[1, K, K, 1], padding='SAME')

    def _display(self, gs):

        fig = plt.figure(figsize=(4, 4))
        graph = gridspec.GridSpec(4, 4)
        graph.update(wspace=0.05, hspace=0.05)
        for i, sample in enumerate(gs):
            ax = plt.subplot(graph[i])
            plt.axis('off')
            ax.set_xticklabels([])
            ax.set_yticklabels([])
            ax.set_aspect('equal')
            plt.imshow(np.squeeze(sample), cmap='Greys_r')
        return fig

    def train(self):
        (x_train, y_train), (_, _) = keras.datasets.cifar10.load_data()
        data = []
        for i in range(x_train.shape[0]):
            if y_train[i] == 1:
                data.append(x_train[i])
        data = np.array(data) / 255.
        sess = tf.Session()
        init = tf.global_variables_initializer()
        sess.run(init)
        saver = tf.train.Saver()

        disp_step_num = 100

        if not os.path.exists('out/'):
            os.makedirs('out/')
        if not os.path.exists('./backup/'):
            os.mkdir('./backup/')
        if not os.path.exists('./backup/cifar10/'):
            os.mkdir('./backup/cifar10/')

        for step in range(self.step_num):
            for _ in range(5):
                indices = np.random.randint(0, data.shape[0], batch_size)
                xs = data[indices]
                zs = sample_z(self.batch_size, self.z_shape)
                _, l_dis = sess.run(
                    [self.opt_dis, self.loss_dis],
                    feed_dict={self.z: zs, self.xv: xs}
                )

            indices = np.random.randint(0, data.shape[0], batch_size)
            xs = data[indices]
            zs = sample_z(self.batch_size, self.z_shape)
            _, l_gen = sess.run([self.opt_gen, self.loss_gen], feed_dict={self.z: zs, self.xv:xs})

            if step % 100 == 0:
                print('Step: {}, loss_dis = {:.5}, loss_gen = {:.5}' .format(step, l_dis, l_gen))
            if step % disp_step_num == 0:
                zs = sample_z(16, self.z_shape)
                gms = sess.run(self.gm, feed_dict={self.z: zs})
                fig = self._display(gms)
                plt.savefig('out/{}.png'.format(str(step).zfill(6)), bbox_inches='tight')
                plt.close(fig)
            if step % 500 == 0:
                saver.save(sess, './backup/cifar10/', write_meta_graph=False)

        sess.close()


if __name__ == '__main__':
    learning_rate = 1e-4
    LAMBDA = 10
    step_num = 100000
    batch_size = 32

    g = ConvWganGpCifar10(
        z_shape=100,
        batch_size=batch_size,
        step_num=step_num,
        learning_rate=learning_rate,
        LAMBDA=LAMBDA,
        DIM=64
    )
    g.train()



