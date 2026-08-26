import client from './client'

export const getSchedule = (days = 7) =>
  client.get('/schedule', { params: { days } }).then(r => r.data)

export const rescheduleSlot = (data) =>
  client.post('/schedule/reschedule', data).then(r => r.data)

