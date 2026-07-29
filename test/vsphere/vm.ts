export default defineEventHandler(async (event) => {
    const config = useRuntimeConfig()

    const vcenter = config.vsphereHost
    const username = config.vsphereUser
    const password = config.vspherePassword

    // 1. Login ke vCenter
    const auth = Buffer.from(`${username}:${password}`).toString('base64')
    const vmsession = await $fetch<{ value: string }>(
        `https://${vcenter}/rest/com/vmware/cis/session`,
        {
            method: 'POST',
            headers: {
                Authorization: `Basic ${auth}`,
            },
        }
    )

    const query= getQuery(event);
    return await $fetch(
        `https://${vcenter}/rest/vcenter/${query?.command}`,
        {
            method: event.method,
            body: event.method === 'POST' ? await readBody(event) : undefined,
            headers: {
                'vmware-api-session-id': vmsession.value,
            },
        }
    )











})
