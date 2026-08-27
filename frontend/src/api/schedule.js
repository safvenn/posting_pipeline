import client from './client'

export const getSchedule = (days = 7) =>
  client.get('/schedule', { params: { days } }).then(r => r.data)

export const rescheduleSlot = (data) =>
  client.post('/schedule/reschedule', data).then(r => r.data)

export const clearFailedSchedules = () =>
  client.post('/schedule/clear-failed').then(r => r.data)

export const deleteScheduledVideo = (data) =>
  client.post('/schedule/delete', data).then(r => r.data)


