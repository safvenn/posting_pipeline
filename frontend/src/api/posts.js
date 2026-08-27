import client from './client'

export const getPosts = (params = {}) =>
  client.get('/posts', { params }).then(r => r.data)

export const getPost = (id) =>
  client.get(`/posts/${id}`).then(r => r.data)

export const deletePost = (id) =>
  client.delete(`/posts/${id}`)

export const retryPost = (id) =>
  client.post(`/posts/${id}/retry`).then(r => r.data)

export const clearFailedPosts = () =>
  client.delete('/posts/failed/clear').then(r => r.data)

export const uploadPost = (formData) =>
  client.post('/posts', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  }).then(r => r.data)

export const publishInstagramReel = (id) =>
  client.post(`/posts/${id}/instagram/publish`).then(r => r.data)


