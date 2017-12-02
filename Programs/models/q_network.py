import torch as t
from torch.nn import Conv1d as conv, SELU, Linear as fc, Softmax, Sigmoid, AlphaDropout, BatchNorm1d as BN, PReLU
import torch.nn as nn
import torch.optim as optim
import numpy as np
from game.game_utils import one_hot_encode_actions


selu = SELU()
softmax = Softmax()
sigmoid = Sigmoid()


def get_shape(x):
    try:
        return x.data.cpu().numpy().shape
    except:
        return x.numpy().shape


def flatten(x):
    shape = get_shape(x)
    return x.resize(shape[0], int(np.prod(shape[1:])))


class CardFeaturizer1(t.nn.Module):
    """
    The one i got results with
    SELU + AlphaDropout + smart initialization
    """
    def __init__(self, hdim, n_filters, cuda=False):
        super(CardFeaturizer1, self).__init__()
        self.hdim = hdim
        self.conv1 = conv(2, n_filters, 1)
        self.conv2 = conv(n_filters, n_filters, 5, padding=2)
        self.conv3 = conv(n_filters, n_filters, 3, padding=1)
        self.conv4 = conv(n_filters, n_filters, 3, dilation=2, padding=2)
        self.conv5 = conv(2, n_filters, 1)

        self.fc1 = fc(13 * n_filters * 3, hdim)
        self.fc2 = fc(13 * 2, hdim)
        self.fc3 = fc(hdim, hdim)
        self.fc4 = fc(4 * n_filters, hdim)
        self.fc5 = fc(52, hdim)
        self.fc6 = fc(hdim, hdim)
        self.fc7 = fc(52, hdim)
        self.fc8 = fc(hdim, hdim)
        self.fc9 = fc(52, hdim)
        self.fc10 = fc(hdim, hdim)
        self.fc11 = fc(3 * hdim, hdim)
        self.fc12 = fc(52, hdim)
        self.fc13 = fc(hdim, hdim)
        self.fc14 = fc(5 * hdim, hdim)
        self.fc15 = fc(hdim, hdim)
        # self.fc17 = fc(hdim, 9)
        self.fc18 = fc(hdim, 1)

        for i in range(1, 19):
            if i == 16 or i == 17:
                continue
            fcc = getattr(self, 'fc' + str(i))
            shape = fcc.weight.data.cpu().numpy().shape
            fcc.weight.data = t.from_numpy(np.random.normal(0, 1 / np.sqrt(shape[0]), shape)).float()

        for i in range(1, 6):
            convv = getattr(self, 'conv' + str(i))
            shape = convv.weight.data.cpu().numpy().shape
            convv.weight.data = t.from_numpy(np.random.normal(0, 1 / np.sqrt(shape[-1] * shape[-2]), shape)).float()

        if cuda:
            # configure the model params on gpu
            self.cuda()


    def forward(self, hand, board):
        dropout = AlphaDropout(.1)
        dropout.training = self.training

        # DETECTING PATTERNS IN THE BOARD AND HAND
        # Aggregate by suit and kind
        color_hand = t.sum(hand, 1)
        color_board = t.sum(t.sum(board, 2), 1)
        kinds_hand = t.sum(hand, -1)
        kinds_board = t.sum(t.sum(board, -1), 1)
        #import pdb; pdb.set_trace()
        colors = t.cat([color_hand.resize(len(color_hand), 1, 4), color_board.resize(len(color_board), 1, 4)], 1)
        kinds = t.cat([kinds_hand.resize(len(kinds_hand), 1, 13), kinds_board.resize(len(kinds_board), 1, 13)], 1)

        # Process board and hand to detect straights using convolutions with kernel size 5, 3, and 3 with dilation
        kinds_straight = selu(dropout(self.conv1((kinds > 0).float())))
        kinds_straight = t.cat([
            selu(dropout(self.conv2(kinds_straight))),
            selu(dropout(self.conv3(kinds_straight))),
            selu(dropout(self.conv4(kinds_straight)))
        ], 1)
        kinds_straight = flatten(kinds_straight)
        kinds_straight = selu(dropout(self.fc1(kinds_straight)))

        # Process board and hand to detect pairs, trips, quads, full houses
        kinds_ptqf = selu(dropout(self.fc2(flatten(kinds))))
        kinds_ptqf = selu(dropout(self.fc3(kinds_ptqf)))

        # Process board and hand to detect flushes
        colors = flatten(selu(dropout(self.conv5(colors))))
        colors = selu(dropout(self.fc4(colors)))

        # Process the board with FC layers
        flop_alone = selu(dropout(self.fc5(flatten(board[:, 0, :, :]))))
        flop_alone = selu(dropout(self.fc6(flop_alone)))
        turn_alone = selu(dropout(self.fc7(flatten(t.sum(board[:, :2, :, :], 1)))))
        turn_alone = selu(dropout(self.fc8(turn_alone)))
        river_alone = selu(dropout(self.fc9(flatten(t.sum(board[:, :3, :, :], 1)))))
        river_alone = selu(dropout(self.fc10(river_alone)))
        board_alone = selu(dropout(self.fc11(t.cat([flop_alone, turn_alone, river_alone], -1))))

        # Process board and hand together with FC layers
        h = selu(dropout(self.fc12(flatten(hand))))
        h = selu(dropout(self.fc13(h)))
        cards_features = selu(dropout(self.fc14(t.cat([h, board_alone, colors, kinds_ptqf, kinds_straight], -1))))
        cards_features = selu(dropout(self.fc15(cards_features)))

        # Predict probabilities of having a given hand + hand strength
        #         probabilities_of_each_combination = softmax(self.fc17(bh))
        hand_strength = sigmoid(self.fc18(cards_features))
        return hand_strength, cards_features, flop_alone, turn_alone, river_alone


def clip_gradients(nn, bound=10):
    for p in nn.parameters():
        if p.grad is not None:
            p.grad = p.grad*((bound <= p.grad).float())*((bound >= p.grad).float()) + bound*((p.grad > bound).float()) - bound*((p.grad < -bound).float())


class SharedNetwork(t.nn.Module):
    def __init__(self, n_actions, hidden_dim):
        super(SharedNetwork, self).__init__()
        self.n_actions = n_actions
        self.hidden_dim = hidden_dim
        hdim = hidden_dim

        # @PROBLEM
        self.fc19 = fc(5 * 6 * 2, hdim)
        self.fc20 = fc(5 * 6 * 2 + hdim, hdim)
        self.fc21 = fc(5 * 6 * 2 + hdim, hdim)
        self.fc22 = fc(5 * 6 * 2 + hdim, hdim)
        self.fc23 = fc(hdim, hdim)
        self.fc24 = fc(5, hdim)
        self.fc25 = fc(3 * hdim, hdim)
        self.fc26 = fc(hdim, hdim)

    def forward(self, cards_features, flop_features, turn_features, river_features, pot, stack, opponent_stack, big_blind, dealer, preflop_plays, flop_plays, turn_plays, river_plays):
        # PROCESS THE ACTIONS THAT WERE TAKEN IN THE CURRENT EPISODE
        processed_preflop = selu(self.fc19(flatten(preflop_plays)))
        processed_flop = selu(self.fc20(t.cat([flatten(flop_plays), flop_features], -1)))
        processed_turn = selu(self.fc21(t.cat([flatten(turn_plays), turn_features], -1)))
        processed_river = selu(self.fc22(t.cat([flatten(river_plays), river_features], -1)))
        plays = selu(self.fc23(processed_preflop + processed_flop + processed_turn + processed_river))

        # add pot, dealer, blinds, dealer, stacks
        pbds = selu(self.fc24(t.cat([pot, stack, opponent_stack, big_blind, dealer], -1)))

        # USE ALL INFORMATION (CARDS/ACTIONS/MISC) TO PREDICT THE Q VALUES
        situation_with_opponent = selu(self.fc25(t.cat([plays, pbds, cards_features], -1)))
        situation_with_opponent = selu(self.fc26(situation_with_opponent))

        return situation_with_opponent


class QNetwork(t.nn.Module):
    def __init__(self,
                 n_actions,
                 hidden_dim,
                 featurizer,
                 game_info,
                 player_id,
                 neural_network_history,
                 is_target_Q=False,
                 shared_network=None,
                 pi_network=None,
                 learning_rate=1e-3,
                 cuda=False):

        super(QNetwork, self).__init__()
        self.n_actions = n_actions
        self.featurizer = featurizer
        self.hidden_dim = hidden_dim
        hdim = self.hidden_dim

        assert not (shared_network is not None and pi_network is not None), "you should provide either pi_network or shared_network"
        if pi_network is not None:
            self.shared_network = pi_network.shared_network
        else:
            if shared_network is not None:
                self.shared_network = shared_network
            else:
                # @PROBLEM
                self.shared_network = SharedNetwork(n_actions, hidden_dim)

        for i in range(19, 27):
            setattr(self, 'fc' + str(i), getattr(self.shared_network, 'fc' + str(i)))
        self.fc27 = fc(hdim, hdim)
        self.fc28 = fc(hdim, n_actions)

        self.criterion = nn.MSELoss()
        self.optim = optim.Adam(self.parameters(), lr=learning_rate)

        # to initialize network on gpu
        if cuda:
            self.cuda()

        # for saving neural network history data
        self.game_info = game_info
        self.player_id = player_id # know the owner of the network
        self.neural_network_history = neural_network_history

    def forward(self, hand, board, pot, stack, opponent_stack, big_blind, dealer, preflop_plays, flop_plays, turn_plays, river_plays):
        HS, flop_features, turn_features, river_features, cards_features = self.featurizer.forward(hand, board)
        # HS, proba_combinations, flop_features, turn_features, river_features, cards_features = self.featurizer.forward(hand, board)
        situation_with_opponent = self.shared_network.forward(cards_features, flop_features, turn_features, river_features, pot, stack, opponent_stack, big_blind, dealer, preflop_plays, flop_plays, turn_plays, river_plays)
        q_values = selu(self.fc27(situation_with_opponent))
        q_values = self.fc28(q_values)

        # for saving neural network history data
        episode_id = self.game_info['#episodes']
        if not episode_id in self.neural_network_history:
            self.neural_network_history[episode_id] = {}
        self.neural_network_history[episode_id][self.player_id] = {}
        self.neural_network_history[episode_id][self.player_id]['q'] = q_values.data.cpu().numpy()

        return q_values

    def learn(self, states, Q_targets, imp_weights):
        self.optim.zero_grad()
        # TODO: support batch forward?
        # not sure if it's supported as it's written now
        Q_preds = self.forward(*states)[:, 0].squeeze()
        loss, td_deltas = self.compute_loss(Q_preds, Q_targets, imp_weights)
        loss.backward()
        # update weights
        self.optim.step()
        return td_deltas

    def compute_loss(self, x, y, imp_weights):
        '''
        compute weighted mse loss
        loss for each sample is scaled by imp_weight
        we need this to account for bias in replay sampling
        '''
        td_deltas = x - y
        mse = t.mean(imp_weights * td_deltas.pow(2))
        return mse, td_deltas


class PiNetwork(t.nn.Module):
    def __init__(self,
                 n_actions,
                 hidden_dim,
                 featurizer,
                 game_info,
                 player_id,
                 neural_network_history,
                 shared_network=None,
                 q_network=None,
                 learning_rate=1e-3,
                 cuda=False):
        super(PiNetwork, self).__init__()
        self.n_actions = n_actions
        self.featurizer = featurizer
        self.hidden_dim = hidden_dim
        hdim = self.hidden_dim

        assert not (shared_network is not None and q_network is not None), "you should provide either q_network or shared_network"
        if q_network is not None:
            self.shared_network = q_network.shared_network
        else:
            if shared_network is not None:
                self.shared_network = shared_network
            else:
                self.shared_network = SharedNetwork(n_actions, hidden_dim)
        for i in range(19, 27):
            setattr(self, 'fc' + str(i), getattr(self.shared_network, 'fc' + str(i)))
        self.fc27 = fc(hdim, hdim)
        self.fc28 = fc(hdim, n_actions)
        self.optim = optim.Adam(self.parameters(), lr=learning_rate)

        if cuda:
            self.cuda()

        # for saving neural network history data
        self.game_info = game_info
        self.player_id = player_id # know the owner of the network
        self.neural_network_history = neural_network_history


    def forward(self, hand, board, pot, stack, opponent_stack, big_blind, dealer, preflop_plays, flop_plays, turn_plays, river_plays):
        HS, flop_features, turn_features, river_features, cards_features = self.featurizer.forward(hand, board)

        #HS, proba_combinations, flop_features, turn_features, river_features, cards_features = self.featurizer.forward(hand, board)

        situation_with_opponent = self.shared_network.forward(cards_features, flop_features, turn_features, river_features, pot, stack, opponent_stack, big_blind, dealer, preflop_plays, flop_plays, turn_plays, river_plays)

        pi_values = selu(self.fc27(situation_with_opponent))
        pi_values = softmax(self.fc28(pi_values))

        # for saving neural network history data
        episode_id = self.game_info['#episodes']
        if not episode_id in self.neural_network_history:
            self.neural_network_history[episode_id] = {}
        self.neural_network_history[episode_id][self.player_id] = {}
        self.neural_network_history[episode_id][self.player_id]['pi'] = pi_values.data.cpu().numpy()

        return pi_values

    def learn(self, states, actions):
        '''    From Torch site
         loss = nn.CrossEntropyLoss()
         input = autograd.Variable(torch.randn(3, 5), requires_grad=True)
         target = autograd.Variable(torch.LongTensor(3).random_(5))
         output = loss(input, target)
         output.backward()
        '''
        self.optim.zero_grad()
        pi_preds = self.forward(*states).squeeze()
        loss = nn.CrossEntropyLoss()
        output = loss(pi_preds, (1+one_hot_encode_actions(actions)).long())
        output.backward()
        self.optim.step()
