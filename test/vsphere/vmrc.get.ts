export default defineEventHandler(async (event) => {
    const config = useRuntimeConfig()

    const vcenter = config.vsphereHost
    const username = config.vsphereUser
    const password = config.vspherePassword

    const query =  getQuery(event);


    // 1. Login ke vCenter
    const auth = Buffer.from(`${username}:${password}`).toString('base64')
    const session = await $fetch<{ value: string }>(
        `https://${vcenter}/rest/com/vmware/cis/session`,
        {
            method: 'POST',
            headers: {
                Authorization: `Basic ${auth}`,
            },
        }
    )

    // 2. Get VM Ticket
    const ticket = await $fetch(
        `https://${vcenter}/rest/vcenter/vm/${query.vm}/console/tickets`,
        {
            method: 'POST',
            headers: {
                'vmware-api-session-id': session.value,
            },
            body: {
                "spec": {
                    "type": "VMRC"
                }
            }
        }
    )
    return ticket
})
