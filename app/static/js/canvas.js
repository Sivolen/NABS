        //const devices_count = {
        //              'Total': 132,
        //              'Cisco': 108,
        //              'Eltex': 1,
        //              'Huawei': 15,
        //              'None': 8
        //            };
            const labels = Object.keys(devices_count);
                const data = Object.values(devices_count);

                const ctx = document.getElementById('myChart').getContext('2d');
                new Chart(ctx, {
                  type: 'pie',
                  data: {
                    labels: labels,
                    datasets: [{
                      label: 'Круговая диаграмма',
                      data: data,
                      backgroundColor: ['red', 'blue', 'green', 'orange', 'purple']
                    }]
                  },
                });