import numpy as np
import math

# Reconstructing the data grid from the image
# Rows: Antony, Brutus, Caesar, Calpurnia, Cleopatra, mercy, worser
# Columns: Antony and Cleopatra, Julius Caesar, The Tempest, Hamlet, Othello, Macbeth
data = np.array([
    [157, 73, 0, 0, 0, 0],  # Antony
    [4, 157, 0, 1, 0, 0],  # Brutus
    [232, 227, 0, 2, 1, 1],  # Caesar
    [0, 10, 0, 0, 0, 0],  # Calpurnia
    [57, 0, 0, 0, 0, 0],  # Cleopatra
    [2, 0, 3, 5, 5, 1],  # mercy
    [2, 0, 1, 1, 1, 0]   # worser
])

print(data)
print()

data = data.astype(float)

condicion = data > 0
resultado = np.zeros_like(data)

tf = np.log10(data, where=condicion, out=resultado)
tf[condicion] += 1

print(tf)

df = np.sum((condicion).astype(int), axis=1)

print(df)

idf = np.log10(6/df)

print(idf)

tf_idf = []
for i in range(len(idf)):
  tf_idf.append(tf[i]*idf[i])
tf_idf = np.array(tf_idf)

print(tf_idf)

tf_idf_unitario = tf_idf[:]

#posible solucion ma rapida traspuesta pero estoy mimido xdd
for i in range(np.shape(tf_idf_unitario)[1]):
  tf_idf_unitario[:,i] = tf_idf_unitario[:,i]/np.linalg.norm(tf_idf_unitario[:,i])

print(tf_idf_unitario)


similitudes = np.dot(tf_idf_unitario.T,tf_idf_unitario)

print(similitudes)

disimilitudes = 1. - similitudes

print(disimilitudes)
