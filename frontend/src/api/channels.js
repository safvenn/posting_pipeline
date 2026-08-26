import client from './client'
export const getChannels = () => client.get('/channels').then(r => r.data)
export const getChannel = (ch) => client.get(`/channels/${ch}`).then(r => r.data)
